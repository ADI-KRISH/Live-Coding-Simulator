"""Thin wrapper over the Anthropic Messages API.

If ANTHROPIC_API_KEY is not set, or a call fails, methods return None and the
helper/judge fall back to their rule-based paths, so the app always works offline.
"""
from __future__ import annotations

import json
import logging
import re

from . import config

log = logging.getLogger("lcs.llm")

try:
    from anthropic import AsyncAnthropic
except Exception:  # pragma: no cover
    AsyncAnthropic = None


class LLM:
    def __init__(self):
        self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) \
            if (AsyncAnthropic and config.ANTHROPIC_API_KEY) else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def text(self, *, model: str, system: str, user: str,
                   max_tokens: int = 400, temperature: float = 0.3) -> str | None:
        if not self.client:
            return None
        try:
            msg = await self.client.messages.create(
                model=model, system=system, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "user", "content": user}],
            )
            parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
            out = "".join(parts).strip()
            return out or None
        except Exception as e:
            log.warning("LLM call failed: %s", e)
            return None

    async def json(self, **kwargs) -> dict | None:
        raw = await self.text(**kwargs)
        if not raw:
            return None
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


llm = LLM()


def numbered(code: str) -> str:
    return "\n".join(f"{i + 1:>3} | {line}" for i, line in enumerate(code.splitlines()))
