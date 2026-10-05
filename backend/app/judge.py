"""The judge. Independent of the helper: it sees code, test outcomes and how many
hints were used (for the process score), never the hint text itself.

Score out of 100:
  correctness 50  visible + hidden tests
  efficiency  15  stress tests (large inputs under a time limit), cut by a third when the
                  measured growth is a worse complexity class than the problem's optimal
  quality     15  LLM rubric review (heuristic fallback offline)
  process     20  hint usage and debugging behaviour
"""
from __future__ import annotations

import math
import statistics
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

# Empirical complexity: time the code at doubling input sizes and fit time ~ n^exponent.
SCALE_SIZES = (500, 1000, 2000, 4000, 8000, 16000, 32000, 64000)
SCALE_TIME_LIMIT = 1.0
SLOWER_THAN_OPTIMAL = 2 / 3          # efficiency multiplier when the measured class is worse
# (exponent below, label, rank). Rank is what gets compared with the problem's optimal.
GROWTH_CLASSES = [
    (0.5, "O(log n) or better", 0),
    (1.5, "O(n) or O(n log n)", 1),
    (2.5, "O(n^2)", 2),
    (math.inf, "O(n^3) or worse", 3),
]


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


# ------------------------------------------------------------------ measured complexity

async def measure_complexity(problem: Problem, code: str) -> dict | None:
    """Time the code on worst-case inputs of growing size and classify how it scales.

    Returns None when it can't be measured (no generator, or the code fails on these inputs).
    """
    # ponytail: a wall-clock fit over 8 sizes can't tell O(n) from O(n log n), and a very fast
    # linear pass can look flat. Count operations with a tracer if finer classes are needed.
    if problem.scale is None:
        return None
    tests = [TestCase(f"n{n}", problem.scale(n), tier="scale", time_limit=SCALE_TIME_LIMIT)
             for n in SCALE_SIZES]
    ex = await execute(code, problem.function_name, tests, timing=True)
    points, timed_out_at = [], None
    for n, t in zip(SCALE_SIZES, tests):
        raw = ex.tests.get(t.id)
        if raw is None or raw.status not in ("ok", "timeout"):
            break
        if raw.status == "timeout":
            timed_out_at = n
            break
        points.append({"n": n, "ms": max(raw.time_ms, 0.0001)})

    if len(points) >= 2:
        exponent = statistics.linear_regression([math.log(p["n"]) for p in points],
                                                [math.log(p["ms"]) for p in points]).slope
        label, rank = next((label, rank) for limit, label, rank in GROWTH_CLASSES if exponent < limit)
    elif timed_out_at:
        exponent, label, rank = None, "too slow to measure", GROWTH_CLASSES[-1][2]
    else:
        return None
    optimal_rank = 0 if problem.optimal_complexity == "O(log n)" else 1
    return {
        "label": label,
        "exponent": None if exponent is None else round(exponent, 2),
        "matches_optimal": rank <= optimal_rank,
        "points": points,
        "timed_out_at": timed_out_at,
    }


# ------------------------------------------------------------------ final (submit)

def _heuristic_quality(a: CodeAnalysis, problem: Problem, measured: dict | None) -> dict:
    nested = 0 if problem.nested_ok else a.max_loop_depth   # nesting is expected on some problems
    q = 12.0
    if nested >= 3:
        q -= 3
    elif nested == 2:
        q -= 1.5
    if a.function_lines > 40:
        q -= 2
    q -= min(3, a.short_names * 0.5)
    return {
        "quality": max(0, round(q, 1)),
        "complexity": (f"{measured['label']} (measured)" if measured else
                       f"~{'O(n^' + str(a.max_loop_depth) + ')' if a.max_loop_depth > 1 else 'O(n)'} (estimated from loop nesting)"),
        "strengths": ["Solution runs end to end."] if not a.is_stub else [],
        "improvements": (["Reduce nested loops; there is likely a single-pass approach."] if nested >= 2 else [])
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


async def _llm_review(problem: Problem, code: str, graded: list[GradedTest],
                      measured: dict | None) -> dict | None:
    by_tier = {}
    for g in graded:
        d = by_tier.setdefault(g.tier, [0, 0])
        d[1] += 1
        d[0] += g.status == "pass"
    failing = [f"{g.tier} '{g.note}': {g.status}" for g in graded if g.status != "pass"]
    user = (
        f"Problem: {problem.title}\n{problem.statement}\n\nOptimal complexity: {problem.optimal_complexity}\n"
        f"Measured time growth on large inputs: {measured['label'] if measured else 'not measured'}\n\n"
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

    runnable = not (a.syntax_error or a.is_stub)
    measured = await measure_complexity(problem, code) if runnable else None

    correctness = WEIGHTS["correctness"] * core_ratio
    efficiency = WEIGHTS["efficiency"] * stress_ratio
    if measured and not measured["matches_optimal"]:
        efficiency *= SLOWER_THAN_OPTIMAL

    if not runnable:
        review = {"quality": 0, "complexity": "n/a", "strengths": [],
                  "improvements": ["Submit a working implementation."],
                  "summary": "No runnable solution was submitted.", "source": "rule"}
    else:
        review = await _llm_review(problem, code, graded, measured) or _heuristic_quality(a, problem, measured)

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
        "measured_complexity": measured,
        "difficulty": problem.difficulty,
        "topics": problem.topics,
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
