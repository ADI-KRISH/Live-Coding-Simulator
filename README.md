# Livecode: live coding simulator with an auto judge and an adaptive helper

A coder picks a problem and a starting level, then codes in a browser editor. Everything is
streamed over a WebSocket, and two agents react to what they do:

- **The judge** runs the visible examples on every run, shows a live projected score, and on
  submit runs hidden edge cases and large stress inputs, then scores out of 100.
- **The helper** watches for signs of being stuck (idle, repeated failures, repeated errors,
  slow approach) and steps in with hints sized to the coder's level. That level is
  re-estimated live from how they work, so the helper backs off or leans in as the session goes.

Works fully offline. With an `ANTHROPIC_API_KEY`, hints are written by Claude and code quality
is reviewed by Claude; without one, the helper uses each problem's built-in hint ladder and the
judge uses a heuristic quality score.

## Contents

- [Run it](#run-it)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [How it works](#how-it-works)
- [Adding problems](#adding-problems)
- [Sandbox and security](#sandbox-and-security)
- [WebSocket protocol](#websocket-protocol)
- [Tests](#tests)
- [Limits of this MVP](#limits-of-this-mvp)

## Run it

Requires Python 3.12+ (or Docker). No frontend build step.

**Docker (recommended: submitted code runs inside the locked-down container)**

```bash
cp .env.example .env          # optionally add ANTHROPIC_API_KEY
docker compose up --build
# open http://localhost:8000
```

**Local dev**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...  # optional
uvicorn app.main:app --reload
# open http://localhost:8000
```

Pick a problem and a starting level, press **Start session**, and code. `Ctrl/Cmd + Enter`
runs the examples.

## Configuration

All settings are environment variables (see `.env.example`). Every one is optional.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Enables Claude-written hints and code review. Empty means offline fallbacks. |
| `HELPER_MODEL` | `claude-haiku-4-5-20251001` | Model for live hints |
| `JUDGE_MODEL` | `claude-sonnet-5-5` | Model for the final quality review |
| `SANDBOX` | `local` | `local` (subprocess with rlimits) or `judge0` |
| `JUDGE0_URL` | `http://localhost:2358` | Judge0 base URL when `SANDBOX=judge0` |
| `JUDGE0_TOKEN` | empty | Sent as `X-Auth-Token` if set |
| `JUDGE0_PYTHON_ID` | `71` | Judge0 language id for Python 3 |
| `SANDBOX_MEMORY_MB` | `512` | Address-space limit per run |
| `SANDBOX_MAX_SECONDS` | `20` | Overall time budget per run |
| `REDIS_URL` | empty | Mirror sessions to Redis. Empty means in-memory only. |

## Project layout

```
backend/app/
  main.py       FastAPI app: GET /, /api/health, /api/problems, /api/sessions/{id}, WS /ws
  engine.py     per-connection session engine; routes events to judge and helper
  sandbox.py    harness + local and Judge0 runners
  judge.py      grading, live score, final report
  helper.py     trigger policy, hint ladder, hint generation
  session.py    session state, skill estimator, Redis-mirrored store
  analysis.py   AST checks (syntax, loop depth, structure hash)
  problems.py   problem bank with visible / hidden / stress tests
  llm.py        Anthropic wrapper; returns None on failure so callers fall back
  config.py     environment config
backend/tests/  pytest suite
frontend/index.html   single-file UI (Monaco from a CDN, vanilla JS)
SPEC.md         full build specification and acceptance criteria
```

## How it works

```
Browser (Monaco)  --code / run / help / submit-->  Engine (per WebSocket)
                                                    |-- analysis.py   AST checks on every snapshot
                                                    |-- sandbox.py    runs code (local or Judge0)
                                                    |-- judge.py      grades runs, final report
                                                    |-- helper.py     when to speak + hint text
                                                    `-- session.py    state, skill estimate, Redis
                  <--analysis / run_result / live_score / level / hint / final_report--
```

### Reactivity

The editor sends a debounced code snapshot every 1.2s of typing. The engine parses it (no LLM)
and only counts it as activity if the AST actually changed, so cursor wiggling or whitespace
doesn't reset the idle timer. An idle loop checks every 5 seconds.

### Helper: when and how much

| Band | Idle nudge | Failing-run streak | Same-error streak | Cooldown | Max rung |
|---|---|---|---|---|---|
| Beginner | 45s | 2 runs | 2 runs | 30s | 4 (code hint) |
| Intermediate | 90s | 3 runs | 3 runs | 60s | 3 (outline) |
| Advanced | off | 5 runs | off | 150s | 2 (approach) |

Hint rungs: **1 Nudge** (concept or where to look), **2 Approach** (strategy in words),
**3 Outline** (pseudocode), **4 Code hint** (a fragment of at most 3 lines, never the solution).

- Hints escalate one rung only while the coder stays stuck on the same thing (same failing
  examples or same error). A new problem resets to rung 1.
- Proactive hints stop one rung below the band's max; the top rung is only given on request.
- When visible tests pass with nested loops on an O(n) problem, the helper gives one free
  warning that the approach will be slow on large inputs.
- Tune all of this in `POLICY` in `backend/app/helper.py`.

### Live skill estimate

Starts from the declared level (beginner 0.25, intermediate 0.55, advanced 0.8) and moves with
signals: more examples passing (+), passing everything fast without hints (+), asking for a
hint (-), repeating the same error (-), re-running with the same failures (-), syntax errors (-).
Bands: below 0.4 beginner, below 0.7 intermediate, else advanced. Signals live in
`Engine._run` / `Engine._help` in `backend/app/engine.py`.

### Judge: scoring (100)

| Part | Points | How |
|---|---|---|
| Correctness | 50 | visible + hidden tests passed |
| Efficiency | 15 | stress tests passed within their time limit |
| Quality | 15 | Claude review (JSON rubric) or offline heuristic |
| Process | 20 | minus 1/2/4/6 per hint by rung, minus 0.5 per failed run after the 4th (max 5) |

The judge is kept independent from the helper: it never sees hint text, only how many hints of
which rung were used. Expected outputs never enter the sandbox; the sandbox returns what the
function produced and the backend compares.

## Adding problems

Add a `Problem(...)` to `backend/app/problems.py` with a reference solution, starter code,
3 visible, ~4 hidden and ~2 stress tests, and a 4-step fallback hint ladder. Expected values are
computed from the reference at startup. `test_reference_solutions_pass_everything` checks it.

## Sandbox and security

`SANDBOX=local` runs each submission in a subprocess with memory, CPU and file-size limits and
a per-test timer. Inside the provided compose setup that subprocess is also inside a read-only,
capability-dropped, non-root container. That's reasonable for a lab or demo, not for the open
internet: the code can still use the network and read the container's files.

For anything public, use Judge0 (`SANDBOX=judge0`). Self-host it by following the Judge0
deployment guide, put it on the same Docker network, and set `JUDGE0_URL`. `JUDGE0_PYTHON_ID`
must match a Python 3 language id on your instance (`GET /languages`).

## WebSocket protocol

Client to server: `start {problem_id, level}`, `code {code}`, `run {code}`,
`help {code, message?}`, `submit {code}`.

Server to client: `session`, `analysis`, `run_status`, `run_result`, `live_score`, `level`,
`helper_status`, `hint`, `final_report`, `error`.

Sessions are mirrored to Redis (7-day TTL) and readable at `GET /api/sessions/{id}`, which
includes the full run, hint and skill-estimate history for analysis.

## Tests

```bash
cd backend
pip install pytest
python -m pytest -q
```

The suite runs fully offline and covers the sandbox (timeouts, load errors, captured output),
the judge (scoring, process penalties, no hidden inputs in reports), the helper policy for each
band, the offline hint fallbacks, and the WebSocket flow from start to submit.

## Limits of this MVP

- Python only. Adding a language means a new harness and a language id for Judge0.
- No accounts or session resume after a disconnect.
- The level estimate uses hand-tuned weights; log sessions and fit them once you have data.
