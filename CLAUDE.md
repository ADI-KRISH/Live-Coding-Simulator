# Livecode: live coding simulator

Browser-based coding practice with two agents reacting live to the coder:
a **judge** that scores and a **helper** that hints, adapted to the coder's skill level.
Full requirements are in `SPEC.md`. Read it before starting any milestone.

## Stack
- Backend: Python 3.12, FastAPI, WebSockets, `anthropic` SDK (async), Redis (optional), httpx
- Sandbox: subprocess with rlimits (`SANDBOX=local`) or self-hosted Judge0 (`SANDBOX=judge0`)
- Frontend: single `frontend/index.html`, Monaco editor from cdnjs, vanilla JS, no build step
- Tests: pytest

## Layout
```
backend/app/
  main.py       FastAPI app: GET /, /api/health, /api/problems, /api/sessions/{id}, POST /api/profile, WS /ws
  engine.py     per-connection session engine; routes events to judge/helper
  sandbox.py    harness (run, timing and step-trace modes) + local and Judge0 runners
  judge.py      grading, live score, measured complexity, final report
  helper.py     trigger POLICY, hint ladder, hint generation
  session.py    Session state, skill estimator, Redis-mirrored store
  skills.py     per-topic skill profile (browser-held), skill graph data, recommendations
  analysis.py   AST checks (syntax, loop depth, structure hash)
  problems.py   problem bank with visible/hidden/stress tests
  llm.py        OpenRouter/Anthropic wrapper; returns None on failure so callers fall back
  config.py     env config
backend/tests/  pytest suite
frontend/index.html
```

## Commands
- Run dev server: `cd backend && uvicorn app.main:app --reload` then open http://localhost:8000
- Tests: `cd backend && python -m pytest -q` (POSIX only; on Windows run them in Docker or WSL)
- Docker: `cp .env.example .env && docker compose up --build`

## Rules that must never be broken
1. Expected outputs never enter the sandbox. The harness returns raw function output; `judge.grade()` compares in the backend.
2. The judge never sees hint text. It may only use hint count and rung for the process score.
3. The helper never writes a complete solution and never mentions hidden or stress tests.
4. Every LLM call has a non-LLM fallback. The app must work with no API key (`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`).
5. Hint generation runs as a background task outside the engine lock; runs and submits must never wait on an LLM hint.
6. Activity for idle detection = AST structure change, not keystrokes.
7. Don't add a frontend build step or framework. Keep `index.html` self-contained.

## Conventions
- Async everywhere on the request path. No blocking calls in the event loop.
- Tune behaviour through `POLICY` (helper.py), `WEIGHTS`/`RUNG_PENALTY` (judge.py) and the skill deltas in engine.py, not scattered constants.
- New problems: difficulty (beginner/intermediate/advanced) + topics from `skills.TOPICS` + `scale(n)` generator + reference solution + 3 visible, ~4 hidden, ~2 stress tests + 4-rung fallback hints. `test_reference_solutions_pass_everything` must pass.
- After any change to sandbox, judge, helper or engine: run the full test suite before finishing.
- UI copy: sentence case, plain verbs, errors say what happened and how to fix it.
