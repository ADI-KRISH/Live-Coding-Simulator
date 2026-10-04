"""The helper agent.

Two parts:
  policy    - decides WHEN to speak and HOW MUCH (which hint rung), based on the
              coder's live skill band. Pure rules, no LLM, cheap to evaluate.
  generator - writes the hint text for the chosen rung (LLM, with a fallback ladder).

Hint ladder:
  1 Nudge     name the concept or where to look
  2 Approach  describe the strategy in words
  3 Outline   pseudocode, no Python
  4 Code hint a fragment of at most 3 lines that unblocks the bug
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import config
from .judge import GradedTest
from .llm import llm, numbered
from .problems import Problem
from .session import Session

RUNG_NAMES = {1: "Nudge", 2: "Approach", 3: "Outline", 4: "Code hint"}

# Per-band behaviour. None disables that trigger for the band.
POLICY = {
    "beginner":     {"idle": 45,   "fail_streak": 2, "error_streak": 2,    "cooldown": 30,
                     "max_rung": 4, "escalate_after": 40,  "flag_inefficiency": True},
    "intermediate": {"idle": 90,   "fail_streak": 3, "error_streak": 3,    "cooldown": 60,
                     "max_rung": 3, "escalate_after": 75,  "flag_inefficiency": True},
    "advanced":     {"idle": None, "fail_streak": 5, "error_streak": None, "cooldown": 150,
                     "max_rung": 2, "escalate_after": 150, "flag_inefficiency": False},
}

TRIGGER_LABELS = {
    "request": "You asked for help",
    "idle": "No progress for a while",
    "fail_streak": "Same tests failing across runs",
    "error_streak": "Same error repeating",
    "inefficiency": "Visible tests pass, but the approach may be too slow",
}


@dataclass
class HintDecision:
    trigger: str
    rung: int


def _next_rung(session: Session, signature: str, cap: int, now: float, escalate_after: float,
               force_escalate: bool) -> int:
    """Escalate one rung if the coder is still stuck on the same thing; otherwise restart."""
    same = [h for h in session.hints if h.signature == signature]
    if not same:
        return 1
    last = same[-1]
    if force_escalate or now - last.at >= escalate_after:
        return min(cap, last.rung + 1)
    return min(cap, last.rung)


def decide(session: Session, trigger: str, analysis_flags: dict | None = None) -> HintDecision | None:
    """Return a hint decision, or None if the helper should stay quiet."""
    p = POLICY[session.band]
    now = time.time()
    sig = session.current_signature()
    if trigger == "request":
        return HintDecision("request", _next_rung(session, sig, p["max_rung"], now, 0, True))

    if session.submitted:
        return None
    if trigger == "inefficiency":   # one-shot warning, not subject to the cooldown
        if not p["flag_inefficiency"] or session.inefficiency_flagged:
            return None
        return HintDecision("inefficiency", 1)
    last = session.last_hint()
    if last and now - last.at < p["cooldown"]:
        return None

    proactive_cap = max(1, p["max_rung"] - 1)   # the top rung is only given on request

    if trigger == "idle":
        # a hint restarts the quiet timer: give the coder time to act on it before nudging again
        quiet_since = max(session.last_activity, last.at if last else 0)
        if p["idle"] is None or now - quiet_since < p["idle"]:
            return None
        if last and last.trigger == "idle" and last.at > session.last_activity:
            return None                          # already nudged during this quiet spell
    elif trigger == "fail_streak":
        if p["fail_streak"] is None:
            return None
        r = session.last_run()
        if not r or r.error_type or r.passed == r.total:
            return None
        if session.streak(lambda x: x.signature == r.signature) < p["fail_streak"]:
            return None
    elif trigger == "error_streak":
        if p["error_streak"] is None:
            return None
        r = session.last_run()
        if not r or not r.error_type:
            return None
        if session.streak(lambda x: x.error_type == r.error_type) < p["error_streak"]:
            return None
    else:
        return None

    return HintDecision(trigger, _next_rung(session, sig, proactive_cap, now, p["escalate_after"], False))


# ------------------------------------------------------------------ generation

STYLE = {
    "beginner": "Be warm and concrete. Point to the exact line number when relevant. Plain language, no jargon without a short explanation.",
    "intermediate": "Open with one guiding question, then give a short pointer. Assume they know standard data structures.",
    "advanced": "Be terse: one or two sentences. Assume strong fundamentals. Never over-explain.",
}

RUNG_RULES = {
    1: "Rung 1 (Nudge): name the concept or the part of the code to look at. Do not describe the algorithm.",
    2: "Rung 2 (Approach): describe the strategy in words. No code and no pseudocode.",
    3: "Rung 3 (Outline): give a pseudocode outline of at most 6 short lines. Do not write Python syntax.",
    4: "Rung 4 (Code hint): give one Python fragment of at most 3 lines that unblocks the specific issue, plus one sentence. Never write the whole function.",
}

SYSTEM = """You are the helper in a live coding practice session. You coach; you never solve.
Hard rules:
- Never write the complete solution or the complete function.
- Never mention hidden tests or stress tests; you only know about the visible examples.
- Do not repeat a previous hint; build on it.
- Maximum 80 words. No greetings, no sign-off, no headings.
- If the coder's current code is already on the right track, say so briefly and address only the gap.
Follow the coder-level style and the hint rung exactly."""


def _run_context(visible: list[GradedTest] | None) -> str:
    if not visible:
        return "They have not run their code yet."
    lines = []
    for g in visible:
        if g.status == "pass":
            lines.append(f"- {g.id} passed")
        elif g.status in ("error",) and g.error:
            lines.append(f"- {g.id} raised {g.error.get('type')}: {g.error.get('message')} (line {g.error.get('line')})")
        elif g.status == "timeout":
            lines.append(f"- {g.id} timed out")
        else:
            lines.append(f"- {g.id} input={g.args!r} expected={g.expected!r} got={g.got!r}")
    return "Latest run on visible examples:\n" + "\n".join(lines)


def _fallback(problem: Problem, rung: int, trigger: str, visible: list[GradedTest] | None,
              syntax: dict | None) -> str:
    if syntax:
        return f"Line {syntax.get('line')} doesn't parse ({syntax.get('message')}). Check brackets, colons and indentation there."
    if trigger == "inefficiency":
        return ("Your examples pass, but nested loops get slow quickly as the input grows. "
                f"Can you get this to {problem.optimal_complexity}?")
    prefix = ""
    if visible:
        bad = next((g for g in visible if g.status != "pass"), None)
        if bad is not None and bad.status == "fail":
            prefix = f"Example {bad.id} expected {bad.expected!r} but got {bad.got!r}. "
        elif bad is not None and bad.error:
            prefix = f"Example {bad.id} raised {bad.error.get('type')} on line {bad.error.get('line')}. "
    return prefix + problem.hints[rung - 1]


async def generate(session: Session, problem: Problem, decision: HintDecision,
                   code: str, visible: list[GradedTest] | None, syntax: dict | None,
                   user_message: str = "") -> str:
    band = session.band
    previous = [f"[rung {h.rung}] {h.text}" for h in session.hints[-4:]]
    situation = {
        "request": f"The coder asked for help.{(' Their message: ' + user_message) if user_message else ''}",
        "idle": f"The coder has made no meaningful change for about {int(time.time() - session.last_activity)} seconds.",
        "fail_streak": "The same visible examples have failed on several consecutive runs.",
        "error_streak": "The same runtime error has repeated on several consecutive runs.",
        "inefficiency": (f"All visible examples pass, but the code has nested loops and the optimal complexity is "
                         f"{problem.optimal_complexity}. Gently warn that this will be slow on large inputs, without giving the approach."),
    }[decision.trigger]

    user = (
        f"Coder level: {band}. Style: {STYLE[band]}\n"
        f"{RUNG_RULES[decision.rung]}\n\n"
        f"Problem: {problem.title}\n{problem.statement}\n\n"
        f"Current code:\n{numbered(code) or '(empty)'}\n\n"
        f"{_run_context(visible)}\n"
        f"{('Parser error: ' + str(syntax)) if syntax else ''}\n\n"
        f"Situation: {situation}\n\n"
        f"Previous hints (do not repeat): {previous or 'none'}"
    )
    text = await llm.text(model=config.HELPER_MODEL, system=SYSTEM, user=user,
                          max_tokens=300, temperature=0.4)
    return text or _fallback(problem, decision.rung, decision.trigger, visible, syntax)
