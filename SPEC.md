# Livecode: build specification

## 1. Goal
A live coding simulator. A coder picks a problem and a starting level, writes Python in a
browser editor, and two agents react in real time:

- **Judge**: grades every run against visible examples (live projected score) and, on submit,
  runs hidden edge cases and large stress inputs, then produces a score out of 100 with feedback.
- **Helper**: detects when the coder is stuck and gives hints whose timing and depth depend on
  the coder's skill level. The level is re-estimated continuously from behaviour.

Must run fully offline (rule-based fallbacks) and get better with an Anthropic API key.

## 2. Architecture
```
Browser (Monaco)
   | WebSocket /ws  (JSON events)
Engine (one per connection, asyncio.Lock around event handling)
   |-- analysis.py  AST checks on every code snapshot (no LLM)
   |-- sandbox.py   execute(code, function_name, tests) -> raw outputs
   |-- judge.py     grade(), live_score(), final_report()
   |-- helper.py    decide() policy + generate() hint text
   `-- session.py   Session dataclass, skill estimator, SessionStore (memory + Redis mirror)
```

## 3. WebSocket protocol
Client -> server
| type | payload | effect |
|---|---|---|
| start | problem_id, level (beginner/intermediate/advanced) | new Session, sends `session` + `level`, starts idle loop |
| code | code | debounced snapshot (client sends 1.2s after last keystroke); updates analysis; counts as activity only if AST structure hash changed |
| run | code | run visible tests, send results, update skill, maybe proactive hint |
| help | code, message? | explicit hint request (always answered) |
| submit | code | final judging, session locked |

Server -> client: `session`, `analysis`, `run_status`, `run_result`, `live_score`, `level`,
`helper_status` (thinking/idle/busy), `hint`, `final_report`, `error`.

## 4. Sandbox
- Harness is a Python script that reads JSON from stdin: `{nonce, code, function, tests:[{id,args,time_limit}]}`.
- It `exec`s user code as `solution.py` with a 2s load timer, looks up the target function,
  then calls it per test with deep-copied args under `signal.setitimer` (timeout exception
  derives from `BaseException` so `except Exception` in user code can't swallow it).
- User `print` output is captured, not mixed with results. Results are emitted as
  `<nonce>{json}` lines: `test` (status ok/error/timeout, got, time_ms, error{type,message,line}),
  `load_error`, `done` (captured stdout, last 4000 chars).
- Error line numbers come only from `solution.py` frames.
- Local runner: `python -I -S`, temp dir cwd, minimal env, rlimits (AS 512MB, CPU, FSIZE 1MB),
  `setsid`, overall budget = sum(time limits)+3s capped at 20s, stream stdout (8MB cap), on
  overall timeout kill the process group and mark unfinished tests as timeout.
- Judge0 runner: POST `/submissions?base64_encoded=false&wait=true` with the harness as source
  and the payload as stdin; same parser.

## 5. Problems
Each problem: id, title, difficulty, function_name, statement (light markdown with backticks),
starter_code, reference solution, compare mode (`exact` | `unordered`), optimal_complexity,
expected_minutes, 4 fallback hints (one per rung), and three test tiers:
- visible (3): shown to the coder, run on every Run
- hidden (~4): edge cases, submit only
- stress (~2): large inputs, 1.5s limit each, submit only; an O(n^2) solution must time out

Expected values are computed from the reference at startup. Ship at least: two sum,
valid brackets, longest substring without repeats, merge intervals.

## 6. Helper
### 6.1 Hint ladder
1 Nudge (concept / where to look) · 2 Approach (strategy in words, no code) ·
3 Outline (pseudocode ≤6 lines, no Python) · 4 Code hint (≤3-line fragment, never full solution).

### 6.2 Policy per live band
| Band | Idle trigger | Fail streak | Same-error streak | Cooldown | Max rung | Escalate after | Inefficiency warning |
|---|---|---|---|---|---|---|---|
| beginner | 45s | 2 | 2 | 30s | 4 | 40s | yes |
| intermediate | 90s | 3 | 3 | 60s | 3 | 75s | yes |
| advanced | off | 5 | off | 150s | 2 | 150s | no |

Rules:
- Explicit requests ignore cooldown and escalate one rung each time on the same stuck signature, capped at max rung.
- Proactive hints are capped at max_rung − 1 (min 1) and escalate only if still stuck after "escalate after".
- Stuck signature = last run's state: `err:<Type>:<line>`, `fail:<ids>`, `pass`, or `no-run`. New signature resets to rung 1.
- Only one idle hint per quiet spell. Any hint restarts the idle timer, so an idle hint never lands right after another hint.
- Inefficiency: when all visible pass, loop depth ≥2 and optimal is O(n)/O(n log n), give one free rung-1 warning (bypasses cooldown, no process penalty).
- Only one hint in flight; a second request while generating returns `helper_status: busy`.

### 6.3 Generation
LLM prompt includes: band + style (beginner warm and concrete with line numbers; intermediate
one guiding question then pointer; advanced terse), rung rule, problem, numbered code, visible
run results (input/expected/got/errors), parser error, trigger situation, last 4 hints.
System rules: never full solution, never mention hidden/stress tests, don't repeat, ≤80 words.
Fallback: prefix with the concrete failing example, then the problem's rung hint.

## 7. Skill estimator
Priors: beginner 0.25, intermediate 0.55, advanced 0.8. Bands: <0.4 beginner, <0.7 intermediate, else advanced.
Deltas: +0.02 per newly passing visible example (max +0.06 per run); +0.05 once for all visible
passing within half the expected time with no hints; −0.03 per help request; −0.02 same error
type as previous run; −0.01 same failing signature as previous run; −0.01 syntax-error run.
Clamp to [0.05, 0.95]. Record history. Send `level` with `changed` so the UI can flag band shifts.

## 8. Judge
Weights: correctness 50 (visible+hidden pass ratio), efficiency 15 (stress pass ratio),
quality 15 (LLM rubric), process 20.
Process = 20 − hint penalties (rung 1/2/3/4 = 1/2/4/6, inefficiency warning free) −
0.5 per failed run beyond the 4th (max 5). Clamp at 0.
Live score after each run: projected correctness from visible + current process.
Quality: LLM returns JSON `{quality 0-15, complexity, strengths[≤3], improvements[≤3], summary}` at
temperature 0. Fallback heuristic: 12 − loop-depth penalty − long function − short names.
Stub or syntax-error submissions get quality 0.
Final report: total, breakdown, per-tier pass counts with case notes (never hidden inputs),
complexity vs optimal, strengths, improvements, hints used, runs, time, declared vs final level.

## 9. Frontend
Single `index.html`. Top bar: wordmark, problem + level selects, start button, clock, live
helper-level chip (flashes on band change), and a segmented score bar sized by weight
(correctness/efficiency/quality/process; striped while projected, solid after submit) with total.
Three columns: problem (statement, examples, note about hidden/stress counts) | editor + action
bar (Run examples, Submit for judging, status) + results (per-example pass/fail/error/timeout
with input/expected/got, captured stdout, Monaco error marker on the failing line) | helper
(mode description for the current band, hint feed with a 4-step ladder glyph, rung name and
trigger reason, optional message box + Ask for a hint). Final report modal.
Ctrl/Cmd+Enter runs. Responsive below 1100px. Reduced motion respected. Visible focus.
Palette: paper #F3F5F7, panel #FFF, ink #16202B, judge #2B59C3, helper #0B7A6B, alert #B4441B.
Fonts: Instrument Sans (UI), JetBrains Mono (code only).

## 10. Deployment
Dockerfile (python:3.12-slim, non-root `runner` user) and docker-compose with redis,
`read_only`, tmpfs /tmp, `cap_drop: ALL`, `no-new-privileges`, pids and memory limits.
`.env.example` documents every variable in `config.py`.
Default models: helper `claude-haiku-4-5-20251001`, judge `claude-sonnet-5-5` (env-overridable).

## 11. Milestones and acceptance criteria
1. **Sandbox + problems**: reference solutions pass every tier for every problem; O(n^2) two-sum times out only on stress; syntax error and top-level infinite loop return load errors within 3s.
2. **Judge**: final report for good vs slow two-sum: both 50 correctness, 15 vs 0 efficiency.
3. **Engine + protocol**: WebSocket start → submit flow works in a TestClient test.
4. **Helper policy**: fail-streak thresholds 2/3/5 by band; advanced explicit requests escalate 1,2,2,2.
5. **Helper generation + LLM review** with fallbacks verified by running with no API key.
6. **Frontend** wired to every server event.
7. **Docker** builds and serves on :8000.
All pytest tests pass at every milestone.

## 12. Out of scope (for now)
Multiple languages, accounts, session resume after disconnect, multiplayer, learned level model.
