"""Per-topic skill profile: how good the coder is at each data structure / algorithm.

The profile is `{"skills": {topic: 0..1}, "solved": [problem ids]}` on the same 0..1 scale as
the session's live level, so `band_for` applies to it too. A topic the coder has never
practised falls back to the level they declared.

It drives three things:
  hints            a session starts at the coder's skill in that problem's topics, so the helper
                   says little on strong topics and more on weak ones (engine.py)
  skill graph      `view()` feeds the chart in the UI
  recommendations  `recommend()` picks problems whose difficulty matches each topic's skill
"""
from __future__ import annotations

from .problems import PROBLEMS, Problem
from .session import LEVEL_PRIORS, band_for

TOPICS = {
    "arrays": "Arrays",
    "hashmaps": "Hash maps",
    "strings": "Strings",
    "stacks": "Stacks and queues",
    "two-pointers": "Two pointers",
    "sorting": "Sorting",
    "binary-search": "Binary search",
    "dp": "Dynamic programming",
    "graphs": "Graphs",
}

LEARN_RATE = 0.4      # how far one judged session moves a topic towards its target
PASS_MARK = 0.6       # share of the 100 points that counts as solving the problem
_ORDER = ["beginner", "intermediate", "advanced"]


def _clamp(v: float) -> float:
    return max(0.05, min(0.95, v))


def clean(raw) -> dict:
    """The profile comes from the browser, so treat it as untrusted input."""
    # ponytail: profile lives in the browser's localStorage (no accounts). Move it server-side,
    # keyed by user, once there is a login.
    raw = raw if isinstance(raw, dict) else {}
    skills = raw.get("skills") if isinstance(raw.get("skills"), dict) else {}
    solved = raw.get("solved") if isinstance(raw.get("solved"), list) else []
    return {
        "skills": {t: round(_clamp(float(v)), 3) for t, v in skills.items()
                   if t in TOPICS and isinstance(v, (int, float)) and v == v},
        "solved": [p for p in PROBLEMS if p in solved],
    }


def clean_level(level) -> str:
    return level if level in LEVEL_PRIORS else "intermediate"


def topic_skill(profile: dict, topic: str, declared: str) -> float:
    return profile["skills"].get(topic, LEVEL_PRIORS[declared])


def start_level(profile: dict, problem: Problem, declared: str) -> float:
    """Where a session on this problem starts: the coder's average skill in its topics."""
    values = [topic_skill(profile, t, declared) for t in problem.topics] or [LEVEL_PRIORS[declared]]
    return sum(values) / len(values)


def update(profile: dict, problem: Problem, score: float, declared: str) -> dict:
    """Fold a judged session (score out of 100) into the profile. Returns {topic: {before, after}}.

    A solved problem can only raise a topic, towards a target just above the problem's own
    difficulty. A failed one can only lower it, towards a target below that difficulty. So acing
    easy problems never makes anyone "advanced", and failing a hard one doesn't sink a beginner.
    """
    perf = max(0.0, min(1.0, score / 100))
    solved = perf >= PASS_MARK
    difficulty = LEVEL_PRIORS[problem.difficulty]
    target = difficulty + 0.25 * perf if solved else difficulty * perf / PASS_MARK
    changes = {}
    for t in problem.topics:
        before = topic_skill(profile, t, declared)
        move = LEARN_RATE * (target - before)
        if (move > 0) != solved:
            move = 0.0
        after = round(_clamp(before + move), 3)
        profile["skills"][t] = after
        changes[t] = {"before": round(before, 3), "after": after}
    if solved and problem.id not in profile["solved"]:
        profile["solved"].append(problem.id)
    return changes


def recommend(profile: dict, declared: str, k: int = 3) -> list[dict]:
    """Unsolved problems first, then the best difficulty match, then the weakest topics."""
    ranked = []
    for p in PROBLEMS.values():
        skill = start_level(profile, p, declared)
        gap = abs(LEVEL_PRIORS[p.difficulty] - skill)
        ranked.append((p.id in profile["solved"], round(gap, 1), skill, p))
    ranked.sort(key=lambda r: r[:3])
    out = []
    for _, _, skill, p in ranked[:k]:
        band = band_for(skill)
        topics = " and ".join(TOPICS[t].lower() for t in p.topics[:2])
        step = _ORDER.index(p.difficulty) - _ORDER.index(band)
        reason = (f"Matches your {band} level in {topics}." if step == 0 else
                  f"A step up from your {band} level in {topics}." if step > 0 else
                  f"Rebuilds the basics in {topics}.")
        out.append({**p.summary(), "reason": reason})
    return out


def view(profile: dict, declared: str) -> dict:
    """Everything the UI needs to draw the skill graph and the recommendations."""
    return {
        "topics": [{"id": t, "label": label, "value": round(topic_skill(profile, t, declared), 3),
                    "band": band_for(topic_skill(profile, t, declared)), "practised": t in profile["skills"]}
                   for t, label in TOPICS.items()],
        "recommendations": recommend(profile, declared),
        "solved": profile["solved"],
    }
