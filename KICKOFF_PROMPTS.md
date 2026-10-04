# Prompts to paste into Claude Code

Put `CLAUDE.md` and `SPEC.md` in the repo root first.

## Option A: you already have the generated code (live-coding-sim.zip)
Unzip it into the repo, then paste:

> Read CLAUDE.md and SPEC.md, then read every file in backend/app and frontend/index.html.
> Run `cd backend && pip install -r requirements.txt pytest && python -m pytest -q` and fix
> anything that fails. Then start the server, and walk through SPEC.md section 11 milestone by
> milestone, checking the code against each acceptance criterion. List any gaps you find
> before changing anything, then fix them one at a time, running the tests after each fix.

## Option B: build from scratch
> Read CLAUDE.md and SPEC.md fully. Build the project milestone by milestone following
> SPEC.md section 11. For each milestone: write the code, write the pytest tests for its
> acceptance criteria, run them, and don't move on until they pass. Respect every rule in
> CLAUDE.md "Rules that must never be broken". Start with milestone 1 and show me the plan for
> it before writing code.

## Useful follow-ups
- "Add 6 more problems (2 easy, 3 medium, 1 hard) following the problem format in SPEC.md section 5. Make sure each stress test makes an O(n^2) solution time out."
- "Add JavaScript support: a Node harness, language select in the UI, Judge0 language id config."
- "Log every session's level history and hint usage to Redis and add GET /api/analytics with averages per problem and band."
- "Add session resume: on reconnect with ?session=<id>, restore state from Redis."
- "Plug this into my adaptive interview platform as a 'coding round' node: expose the final report as a structured result the orchestrator can consume."
