"""The judge. Independent of the helper: it sees code, test outcomes and how many
hints were used (for the process score), never the hint text itself.

Score out of 100:
  correctness 50  visible + hidden tests
  efficiency  15  stress tests (large inputs under a time limit)
  quality     15  LLM rubric review (heuristic fallback offline)
  process     20  hint usage and debugging behaviour
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict

from . import config
from .analysis import CodeAnalysis, analyze
from .llm import llm, numbered
from .problems import Problem, TestCase
from .sandbox import ExecutionResult, execute
from .session import Session

WEIGHTS = {"correctness": 50, "efficiency": 15, "quality": 15, "process": 20}
RUNG_PENALTY = {1: 1.0, 2: 2.0, 3: 4.0, 4: 6.0}


@dataclass
class GradedTest:
    id: str
    tier: str
    status: str            # pass | fail | error | timeout | not_run
    time_ms: float
    note: str
    args: list | None = None       # only filled for visible tests
    expected: object = None        # only filled for visible tests
    got: object = None             # only filled for visible tests
    error: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _equal(got, expected, mode: str) -> bool:
    if mode == "unordered":
        try:
            return isinstance(got, list) and sorted(got) == sorted(expected)
        except TypeError:
            return False
    if isinstance(expected, bool):
        return isinstance(got, (bool, int)) and got in (0, 1) and bool(got) == expected
    if isinstance(expected, float) or isinstance(got, float):
        try:
            return abs(float(got) - float(expected)) <= 1e-6 * max(1.0, abs(float(expected)))
        except (TypeError, ValueError):
            return False
    return got == expected


def grade(problem: Problem, tests: list[TestCase], ex: ExecutionResult) -> list[GradedTest]:
    out = []
    for t in tests:
        visible = t.tier == "visible"
        if ex.load_error:
            status, raw = "error", None
        else:
            raw = ex.tests.get(t.id)
            if raw is None or raw.status == "not_run":
                status = "not_run"
            elif raw.status == "timeout":
                status = "timeout"
            elif raw.status == "error":
                status = "error"
            else:
                status = "pass" if _equal(raw.got, t.expected, problem.compare) else "fail"
        g = GradedTest(
            id=t.id, tier=t.tier, status=status,
            time_ms=raw.time_ms if raw else 0.0, note=t.note,
            error=(ex.load_error if ex.load_error else (raw.error if raw else None)),
        )
        if visible:
            g.args, g.expected = t.args, t.expected
            g.got = raw.got if raw else None
        out.append(g)
    return out


# ------------------------------------------------------------------ live (every run)

def live_score(session: Session, graded_visible: list[GradedTest]) -> dict:
    total = len(graded_visible) or 1
    passed = sum(1 for g in graded_visible if g.status == "pass")
    projected = round(WEIGHTS["correctness"] * passed / total, 1)
    return {
        "correctness": projected,
        "process": round(process_score(session), 1),
        "visible_passed": passed,
        "visible_total": len(graded_visible),
        "note": "Projected from visible tests. Hidden, stress and quality are scored on submit.",
    }


def process_score(session: Session) -> float:
    # The one-shot inefficiency warning is the helper's initiative, so it is free.
    penalty = sum(RUNG_PENALTY.get(h.rung, 2.0) for h in session.hints if h.trigger != "inefficiency")
    failed_runs = sum(1 for r in session.runs if r.passed < r.total)
    penalty += min(5.0, max(0, failed_runs - 4) * 0.5)
    return max(0.0, WEIGHTS["process"] - penalty)


# ------------------------------------------------------------------ final (submit)

def _heuristic_quality(a: CodeAnalysis) -> dict:
    q = 12.0
    if a.max_loop_depth >= 3:
        q -= 3
    elif a.max_loop_depth == 2:
        q -= 1.5
    if a.function_lines > 40:
        q -= 2
    q -= min(3, a.short_names * 0.5)
    return {
        "quality": max(0, round(q, 1)),
        "complexity": f"~{'O(n^' + str(a.max_loop_depth) + ')' if a.max_loop_depth > 1 else 'O(n)'} (estimated from loop nesting)",
        "strengths": ["Solution runs end to end."] if not a.is_stub else [],
        "improvements": (["Reduce nested loops; there is likely a single-pass approach."] if a.max_loop_depth >= 2 else [])
        + (["Use descriptive variable names."] if a.short_names > 2 else []),
        "summary": "Scored with the offline heuristic (no model review was available).",
        "source": "heuristic",
    }


REVIEW_SYSTEM = """You are a strict, fair code reviewer grading a timed coding exercise.
Return ONLY a JSON object, no prose, with keys:
  "quality": integer 0-15 (readability, naming, structure, idiomatic Python, edge-case handling),
  "complexity": string, time and space complexity of the submitted code, e.g. "O(n) time, O(n) space",
  "strengths": list of up to 3 short strings,
  "improvements": list of up to 3 short, specific strings,
  "summary": one sentence.
Grade the code that was written, not the code that should have been written. Correctness is scored
separately from tests; only consider it where it reflects code quality (e.g. unhandled edge cases)."""


async def _llm_review(problem: Problem, code: str, graded: list[GradedTest]) -> dict | None:
    by_tier = {}
    for g in graded:
        d = by_tier.setdefault(g.tier, [0, 0])
        d[1] += 1
        d[0] += g.status == "pass"
    failing = [f"{g.tier} '{g.note}': {g.status}" for g in graded if g.status != "pass"]
    user = (
        f"Problem: {problem.title}\n{problem.statement}\n\nOptimal complexity: {problem.optimal_complexity}\n\n"
        f"Submitted code:\n{numbered(code)}\n\n"
        f"Test results by tier (passed/total): {by_tier}\n"
        f"Failing cases: {failing or 'none'}"
    )
    data = await llm.json(model=config.JUDGE_MODEL, system=REVIEW_SYSTEM, user=user,
                          max_tokens=500, temperature=0.0)
    if not data or "quality" not in data:
        return None
    try:
        data["quality"] = max(0, min(15, float(data["quality"])))
    except (TypeError, ValueError):
        return None
    data["source"] = "llm"
    return data


async def final_report(session: Session, problem: Problem, code: str) -> dict:
    tests = problem.all_tests()
    ex = await execute(code, problem.function_name, tests)
    graded = grade(problem, tests, ex)
    a = analyze(code, problem.function_name)

    core = [g for g in graded if g.tier in ("visible", "hidden")]
    stress = [g for g in graded if g.tier == "stress"]
    core_ratio = sum(g.status == "pass" for g in core) / (len(core) or 1)
    stress_ratio = sum(g.status == "pass" for g in stress) / (len(stress) or 1)

    correctness = WEIGHTS["correctness"] * core_ratio
    efficiency = WEIGHTS["efficiency"] * stress_ratio

    if a.syntax_error or a.is_stub:
        review = {"quality": 0, "complexity": "n/a", "strengths": [],
                  "improvements": ["Submit a working implementation."],
                  "summary": "No runnable solution was submitted.", "source": "rule"}
    else:
        review = await _llm_review(problem, code, graded) or _heuristic_quality(a)

    process = process_score(session)
    breakdown = {
        "correctness": round(correctness, 1),
        "efficiency": round(efficiency, 1),
        "quality": round(float(review["quality"]), 1),
        "process": round(process, 1),
    }
    total = round(sum(breakdown.values()), 1)

    def tier_summary(tier):
        items = [g for g in graded if g.tier == tier]
        return {
            "passed": sum(g.status == "pass" for g in items),
            "total": len(items),
            "cases": [{"note": g.note, "status": g.status, "time_ms": g.time_ms} for g in items],
        }

    return {
        "total": total,
        "max": 100,
        "breakdown": breakdown,
        "weights": WEIGHTS,
        "tiers": {t: tier_summary(t) for t in ("visible", "hidden", "stress")},
        "complexity": review.get("complexity", ""),
        "optimal_complexity": problem.optimal_complexity,
        "strengths": review.get("strengths", []),
        "improvements": review.get("improvements", []),
        "summary": review.get("summary", ""),
        "review_source": review.get("source", ""),
        "hints_used": [{"rung": h.rung, "trigger": h.trigger} for h in session.hints],
        "runs": len(session.runs),
        "time_seconds": round(time.time() - session.started_at),
        "final_level": session.band,
        "declared_level": session.declared_level,
        "sandbox_error": ex.crashed,
    }
