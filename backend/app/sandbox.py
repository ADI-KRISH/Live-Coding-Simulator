"""Executes untrusted code against test inputs.

The harness only ever receives test *arguments*. It returns what the coder's function
produced; correctness is decided in the backend (judge.py) so expected answers for
hidden tests never enter the sandbox.

Two backends:
  local  - subprocess with rlimits. Fine inside the Docker container for dev/demo.
  judge0 - self-hosted Judge0 (recommended for anything public).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import tempfile
from dataclasses import dataclass, field

import httpx

from . import config

HARNESS = r'''
import sys, json, io, time, signal, traceback, copy, contextlib

_payload = json.loads(sys.stdin.read())
_nonce = _payload["nonce"]
_out = sys.stdout
_cap = io.StringIO()

def _emit(obj):
    _out.write(_nonce + json.dumps(obj, default=repr) + "\n")
    _out.flush()

def _err(e):
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == "solution.py"]
    line = frames[-1].lineno if frames else getattr(e, "lineno", None)
    return {"type": type(e).__name__, "message": str(e)[:300], "line": line}

def _jsonable(v):
    try:
        json.dumps(v)
        return v
    except Exception:
        if isinstance(v, (tuple, set, frozenset)):
            return [_jsonable(x) for x in v]
        return repr(v)

class _TimeLimit(BaseException):
    pass

class _StepLimit(BaseException):
    pass

# Step-through mode: record one step per executed line of solution.py (like Python Tutor).
_max_steps = _payload.get("trace") or 0
_steps = []
_trace_from = 0

def _show(v):
    try:
        s = repr(v)
    except Exception:
        s = "<unprintable>"
    return s if len(s) <= 200 else s[:200] + "..."

def _tracer(frame, event, arg):
    if frame.f_code.co_filename != "solution.py":
        return None
    if event in ("line", "return"):
        if len(_steps) >= _max_steps:
            raise _StepLimit()
        stack, f = [], frame
        while f is not None and f.f_code.co_filename == "solution.py":
            stack.append(f.f_code.co_name)
            f = f.f_back
        step = {"line": frame.f_lineno, "event": event, "stack": stack[::-1],
                "locals": {k: _show(v) for k, v in frame.f_locals.items() if not k.startswith("__")},
                "out": len(_cap.getvalue()) - _trace_from}
        if event == "return":
            step["returned"] = _show(arg)
        _steps.append(step)
    return _tracer

def _call(args):
    if _max_steps:
        sys.settrace(_tracer)
    try:
        with contextlib.redirect_stdout(_cap):
            return _fn(*args)
    finally:
        sys.settrace(None)

def _alarm(signum, frame):
    raise _TimeLimit()

signal.signal(signal.SIGALRM, _alarm)
sys.setrecursionlimit(10000)
_ns = {"__name__": "__solution__"}

try:
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    with contextlib.redirect_stdout(_cap):
        exec(compile(_payload["code"], "solution.py", "exec"), _ns)
    signal.setitimer(signal.ITIMER_REAL, 0)
except BaseException as e:
    signal.setitimer(signal.ITIMER_REAL, 0)
    if isinstance(e, _TimeLimit):
        _emit({"kind": "load_error", "error": {"type": "TimeoutError",
               "message": "top-level code ran for more than 2 seconds (infinite loop outside the function?)", "line": None}})
    else:
        _emit({"kind": "load_error", "error": _err(e)})
    _emit({"kind": "done", "stdout": _cap.getvalue()[-4000:]})
    sys.exit(0)

_fn = _ns.get(_payload["function"])
if not callable(_fn):
    _emit({"kind": "load_error", "error": {"type": "NameError",
           "message": "function '%s' is not defined" % _payload["function"], "line": None}})
    _emit({"kind": "done", "stdout": _cap.getvalue()[-4000:]})
    sys.exit(0)

# Timing mode: best of 3 calls per test (less noise), and stop at the first timeout.
_timing = bool(_payload.get("timing"))
_trace_from = len(_cap.getvalue())

for t in _payload["tests"]:
    best = None
    start = time.perf_counter()
    try:
        for _ in range(3 if _timing else 1):
            args = copy.deepcopy(t["args"])
            start = time.perf_counter()
            signal.setitimer(signal.ITIMER_REAL, t["time_limit"])
            got = _call(args)
            signal.setitimer(signal.ITIMER_REAL, 0)
            took = time.perf_counter() - start
            best = took if best is None else min(best, took)
        _emit({"kind": "test", "id": t["id"], "status": "ok", "got": None if _timing else _jsonable(got),
               "time_ms": round(best * 1000, 4)})
    except _TimeLimit:
        _emit({"kind": "test", "id": t["id"], "status": "timeout",
               "time_ms": round(t["time_limit"] * 1000)})
        if _timing:
            break
    except _StepLimit:
        signal.setitimer(signal.ITIMER_REAL, 0)
        _emit({"kind": "test", "id": t["id"], "status": "stopped", "time_ms": 0})
    except BaseException as e:
        signal.setitimer(signal.ITIMER_REAL, 0)
        _emit({"kind": "test", "id": t["id"], "status": "error", "error": _err(e),
               "time_ms": round((time.perf_counter() - start) * 1000, 4)})

if _max_steps:
    _emit({"kind": "trace", "steps": _steps, "stdout": _cap.getvalue()[_trace_from:][:4000]})

_emit({"kind": "done", "stdout": _cap.getvalue()[-4000:]})
'''

MAX_OUTPUT_BYTES = 8 * 1024 * 1024


@dataclass
class RawTestResult:
    id: str
    status: str                # ok | error | timeout | not_run | stopped (step limit while tracing)
    got: object = None
    error: dict | None = None
    time_ms: float = 0.0


@dataclass
class ExecutionResult:
    load_error: dict | None = None
    tests: dict[str, RawTestResult] = field(default_factory=dict)
    stdout: str = ""
    crashed: str | None = None          # sandbox-level failure (killed, OOM, infra)
    trace: dict | None = None           # {steps, stdout} when run with trace > 0


def _payload(code: str, function: str, tests: list, timing: bool = False, trace: int = 0) -> tuple[str, str]:
    nonce = "@@" + secrets.token_hex(12) + "@@"
    data = {
        "nonce": nonce,
        "code": code,
        "function": function,
        "timing": timing,
        "trace": trace,
        "tests": [{"id": t.id, "args": t.args, "time_limit": t.time_limit} for t in tests],
    }
    return nonce, json.dumps(data, ensure_ascii=False)


def _parse(stdout: str, nonce: str, tests: list) -> ExecutionResult:
    res = ExecutionResult()
    saw_done = False
    for line in stdout.splitlines():
        if not line.startswith(nonce):
            continue
        try:
            obj = json.loads(line[len(nonce):])
        except json.JSONDecodeError:
            continue
        kind = obj.get("kind")
        if kind == "load_error":
            res.load_error = obj.get("error")
        elif kind == "test":
            res.tests[obj["id"]] = RawTestResult(
                id=obj["id"], status=obj["status"], got=obj.get("got"),
                error=obj.get("error"), time_ms=obj.get("time_ms", 0.0))
        elif kind == "trace":
            res.trace = {"steps": obj.get("steps", []), "stdout": obj.get("stdout", "")}
        elif kind == "done":
            saw_done = True
            res.stdout = obj.get("stdout", "")
    if not res.load_error:
        for t in tests:
            if t.id not in res.tests:
                res.tests[t.id] = RawTestResult(id=t.id, status="not_run")
    if not saw_done and not res.load_error:
        res.crashed = res.crashed or "Process ended early (memory limit, crash, or overall time limit)."
    return res


# --------------------------------------------------------------------------- local

def _limits():
    import resource
    mem = config.SANDBOX_MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    cpu = int(config.SANDBOX_MAX_SECONDS) + 1
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    os.setsid()


def _budget(tests: list, timing: bool) -> float:
    return min(config.SANDBOX_MAX_SECONDS, sum(t.time_limit for t in tests) * (3 if timing else 1) + 3.0)


async def _run_local(code: str, function: str, tests: list, timing: bool, trace: int) -> ExecutionResult:
    nonce, stdin = _payload(code, function, tests, timing, trace)
    budget = _budget(tests, timing)
    buf = bytearray()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="lcs-") as tmp:
        harness_path = os.path.join(tmp, "harness.py")
        with open(harness_path, "w") as f:
            f.write(HARNESS)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", harness_path,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, cwd=tmp,
            env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
            preexec_fn=_limits if os.name == "posix" else None,
        )

        async def feed_and_read():
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
            proc.stdin.close()
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                if len(buf) < MAX_OUTPUT_BYTES:
                    buf.extend(chunk)
            await proc.wait()

        try:
            await asyncio.wait_for(feed_and_read(), timeout=budget)
        except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError) as e:
            timed_out = isinstance(e, asyncio.TimeoutError)
            try:
                os.killpg(proc.pid, 9)
            except Exception:
                proc.kill()
            await proc.wait()

    res = _parse(buf.decode("utf-8", "replace"), nonce, tests)
    if timed_out:
        for r in res.tests.values():
            if r.status == "not_run":
                r.status = "timeout"
        res.crashed = None
    return res


# --------------------------------------------------------------------------- judge0

async def _run_judge0(code: str, function: str, tests: list, timing: bool, trace: int) -> ExecutionResult:
    nonce, stdin = _payload(code, function, tests, timing, trace)
    wall = _budget(tests, timing)
    body = {
        "source_code": HARNESS,
        "language_id": config.JUDGE0_PYTHON_ID,
        "stdin": stdin,
        "cpu_time_limit": wall,
        "wall_time_limit": wall + 2,
        "memory_limit": config.SANDBOX_MEMORY_MB * 1024,
    }
    headers = {"X-Auth-Token": config.JUDGE0_TOKEN} if config.JUDGE0_TOKEN else {}
    url = f"{config.JUDGE0_URL.rstrip('/')}/submissions?base64_encoded=false&wait=true"
    try:
        async with httpx.AsyncClient(timeout=wall + 15) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # infra failure, not the coder's fault
        return ExecutionResult(crashed=f"Sandbox unavailable: {e}")
    res = _parse(data.get("stdout") or "", nonce, tests)
    status = (data.get("status") or {}).get("description", "")
    if "Time Limit" in status:
        for r in res.tests.values():
            if r.status == "not_run":
                r.status = "timeout"
        res.crashed = None
    return res


async def execute(code: str, function: str, tests: list, timing: bool = False, trace: int = 0) -> ExecutionResult:
    """timing: best-of-3 per test, stop at the first timeout. trace: record up to that many steps."""
    if config.SANDBOX == "judge0":
        return await _run_judge0(code, function, tests, timing, trace)
    return await _run_local(code, function, tests, timing, trace)
