"""Session state, the live skill estimator, and an optional Redis-backed store."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict

from . import config

LEVEL_PRIORS = {"beginner": 0.25, "intermediate": 0.55, "advanced": 0.8}


def band_for(value: float) -> str:
    if value < 0.4:
        return "beginner"
    if value < 0.7:
        return "intermediate"
    return "advanced"


@dataclass
class RunRecord:
    at: float
    passed: int
    total: int
    failing: list[str]
    error_type: str | None
    signature: str


@dataclass
class HintRecord:
    at: float
    rung: int
    trigger: str
    text: str
    signature: str


@dataclass
class Session:
    problem_id: str
    declared_level: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    level_value: float = 0.5
    code: str = ""
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    last_structure: str = ""
    runs: list[RunRecord] = field(default_factory=list)
    hints: list[HintRecord] = field(default_factory=list)
    best_visible_passed: int = 0
    first_full_pass_at: float | None = None
    fast_bonus_given: bool = False
    inefficiency_flagged: bool = False
    submitted: bool = False
    final_report: dict | None = None
    level_history: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self):
        if not self.level_history:
            self.level_value = LEVEL_PRIORS.get(self.declared_level, 0.5)
            self.level_history = [(self.started_at, self.level_value)]

    # ------------------------------------------------------------ derived
    @property
    def band(self) -> str:
        return band_for(self.level_value)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def last_run(self) -> RunRecord | None:
        return self.runs[-1] if self.runs else None

    def last_hint(self) -> HintRecord | None:
        return self.hints[-1] if self.hints else None

    def streak(self, predicate) -> int:
        """How many of the most recent runs in a row satisfy predicate."""
        n = 0
        for r in reversed(self.runs):
            if not predicate(r):
                break
            n += 1
        return n

    def current_signature(self) -> str:
        r = self.last_run()
        return r.signature if r else "no-run"

    # ------------------------------------------------------------ skill estimator
    def nudge_level(self, delta: float) -> bool:
        """Apply a signal to the skill estimate. Returns True if the band changed."""
        before = self.band
        self.level_value = max(0.05, min(0.95, self.level_value + delta))
        self.level_history.append((time.time(), round(self.level_value, 3)))
        return self.band != before

    def to_json(self) -> str:
        return json.dumps(asdict(self))


# ---------------------------------------------------------------- store

class SessionStore:
    """In-memory store, mirrored to Redis when REDIS_URL is set (for review/analytics)."""

    def __init__(self):
        self._mem: dict[str, Session] = {}
        self._redis = None
        if config.REDIS_URL:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(config.REDIS_URL, decode_responses=True)
            except Exception:
                self._redis = None

    async def save(self, s: Session) -> None:
        self._mem[s.id] = s
        if self._redis is not None:
            try:
                await self._redis.set(f"lcs:session:{s.id}", s.to_json(), ex=7 * 24 * 3600)
            except Exception:
                pass

    async def load_raw(self, session_id: str) -> dict | None:
        if session_id in self._mem:
            return json.loads(self._mem[session_id].to_json())
        if self._redis is not None:
            try:
                raw = await self._redis.get(f"lcs:session:{session_id}")
                return json.loads(raw) if raw else None
            except Exception:
                return None
        return None


store = SessionStore()
