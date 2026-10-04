"""Thin wrapper over the LLM provider: OpenRouter (chat completions) or the Anthropic Messages API.

If no API key is set, or a call fails, methods return None and the
helper/judge fall back to their rule-based paths, so the app always works offline.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from . import config

log = logging.getLogger("lcs.llm")

try:
    from anthropic import AsyncAnthropic
except Exception:  # pragma: no cover
    AsyncAnthropic = None


class LLM:
    def __init__(self):
        self.provider = config.LLM_PROVIDER
        self.client = None
        if self.provider == "openrouter" and config.OPENROUTER_API_KEY:
            self.client = httpx.AsyncClient(
                timeout=45, headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"})
        elif self.provider == "anthropic" and AsyncAnthropic and config.ANTHROPIC_API_KEY:
            self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def text(self, *, model: str, system: str, user: str,
                   max_tokens: int = 400, temperature: float = 0.3) -> str | None:
        if not self.client:
            return None
        if self.provider == "openrouter":
            return await self._openrouter(model, system, user, max_tokens, temperature)
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

    async def _openrouter(self, model: str, system: str, user: str,
                          max_tokens: int, temperature: float) -> str | None:
        body = {
            "model": model, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # reasoning tokens count against max_tokens, so leave room for the answer itself
            "max_tokens": max_tokens + (2000 if config.OPENROUTER_REASONING else 0),
            "reasoning": {"enabled": config.OPENROUTER_REASONING},
        }
        try:
            r = await self.client.post(config.OPENROUTER_URL, json=body)
            r.raise_for_status()
            out = (r.json()["choices"][0]["message"].get("content") or "").strip()
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
