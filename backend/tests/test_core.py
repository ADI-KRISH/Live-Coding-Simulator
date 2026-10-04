"""Smoke tests: sandbox, judge and helper policy. Run from backend/: python -m pytest -q"""
import asyncio
import time

from fastapi.testclient import TestClient

from app import helper
from app.judge import final_report, grade
from app.main import app
from app.problems import PROBLEMS
from app.sandbox import execute
from app.session import HintRecord, RunRecord, Session

P = PROBLEMS["two-sum"]
GOOD = ("def two_sum(nums, target):\n    seen = {}\n    for i, x in enumerate(nums):\n"
        "        if target - x in seen:\n            return [seen[target - x], i]\n        seen[x] = i\n")
SLOW = ("def two_sum(nums, target):\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n"
        "            if nums[i] + nums[j] == target:\n                return [i, j]\n")


def run(coro):
    return asyncio.run(coro)


def test_reference_solutions_pass_everything():
    for p in PROBLEMS.values():
        import inspect
        src = inspect.getsource(p.reference).replace(p.reference.__name__, p.function_name, 1)
        ex = run(execute(src, p.function_name, p.all_tests()))
        assert all(g.status == "pass" for g in grade(p, p.all_tests(), ex)), p.id


def test_slow_solution_times_out_on_stress_only():
    ex = run(execute(SLOW, P.function_name, P.all_tests()))
    graded = grade(P, P.all_tests(), ex)
    assert all(g.status == "pass" for g in graded if g.tier != "stress")
    assert all(g.status == "timeout" for g in graded if g.tier == "stress")


def test_syntax_and_infinite_top_level_loop():
    ex = run(execute("def two_sum(:\n", P.function_name, P.visible))
    assert ex.load_error["type"] == "SyntaxError"
    t = time.time()
    ex = run(execute("while True: pass", P.function_name, P.visible))
    assert ex.load_error["type"] == "TimeoutError" and time.time() - t < 3


def test_final_report_scores():
    s = Session("two-sum", "intermediate")
    good = run(final_report(s, P, GOOD))
    slow = run(final_report(s, P, SLOW))
    assert good["breakdown"]["correctness"] == 50 and good["breakdown"]["efficiency"] == 15
    assert slow["breakdown"]["efficiency"] == 0 and slow["total"] < good["total"]


def test_helper_policy_by_level():
    for level, streak_needed in (("beginner", 2), ("intermediate", 3), ("advanced", 5)):
        s = Session("two-sum", level)
        for i in range(streak_needed - 1):
            s.runs.append(RunRecord(time.time(), 1, 3, ["v2", "v3"], None, "fail:v2,v3"))
            assert helper.decide(s, "fail_streak") is None
        s.runs.append(RunRecord(time.time(), 1, 3, ["v2", "v3"], None, "fail:v2,v3"))
        assert helper.decide(s, "fail_streak") is not None, level


def test_explicit_requests_escalate_but_respect_cap():
    s = Session("two-sum", "advanced")
    rungs = []
    for _ in range(4):
        d = helper.decide(s, "request")
        rungs.append(d.rung)
        s.hints.append(HintRecord(time.time(), d.rung, "request", "x", s.current_signature()))
    assert rungs == [1, 2, 2, 2]


def test_websocket_flow():
    c = TestClient(app)
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "problem_id": "two-sum", "level": "beginner"})
        types = []
        while "level" not in types:
            types.append(ws.receive_json()["type"])
        assert types[0] == "session"
        ws.send_json({"type": "submit", "code": GOOD})
        while True:
            m = ws.receive_json()
            if m["type"] == "final_report":
                assert m["report"]["breakdown"]["correctness"] == 50
                break
