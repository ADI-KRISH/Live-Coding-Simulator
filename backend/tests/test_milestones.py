"""Acceptance criteria from SPEC.md section 11 that test_core.py doesn't cover."""
import asyncio
import json
import time

from fastapi.testclient import TestClient

from app import helper
from app.analysis import analyze
from app.judge import final_report, grade, process_score
from app.main import app
from app.problems import PROBLEMS
from app.sandbox import _payload, execute
from app.session import HintRecord, RunRecord, Session, band_for

from .test_core import GOOD, SLOW, P

WRONG = "def two_sum(nums, target):\n    print('dbg')\n    return [0, 1]\n"
RAISES = "def two_sum(nums, target):\n    return nums[99]\n"


def run(coro):
    return asyncio.run(coro)


def fail_run(sig="fail:v2,v3", error_type=None):
    return RunRecord(time.time(), 1, 3, ["v2", "v3"], error_type, sig)


def hint(rung, trigger="request", sig="no-run", age=0.0):
    return HintRecord(time.time() - age, rung, trigger, "x", sig)


# ------------------------------------------------------------------ 1. sandbox + problems

def test_problem_bank_shape():
    assert {"two-sum", "valid-parentheses", "longest-unique-substring", "merge-intervals"} <= set(PROBLEMS)
    for p in PROBLEMS.values():
        assert len(p.visible) == 3 and len(p.hidden) >= 4 and len(p.stress) >= 2 and len(p.hints) == 4
        assert all(t.time_limit == 1.5 for t in p.stress)
        assert all(t.tier == tier for tier in ("visible", "hidden", "stress") for t in getattr(p, tier))


def test_expected_values_never_enter_the_sandbox():
    _, stdin = _payload(GOOD, P.function_name, P.all_tests())
    assert all(set(t) == {"id", "args", "time_limit"} for t in json.loads(stdin)["tests"])


def test_load_errors_return_within_three_seconds():
    for code, kind in (("def two_sum(:\n", "SyntaxError"), ("while True: pass", "TimeoutError")):
        t = time.time()
        ex = run(execute(code, P.function_name, P.visible))
        assert ex.load_error["type"] == kind and time.time() - t < 3


def test_timeout_survives_bare_except_and_stdout_is_captured():
    code = ("def two_sum(nums, target):\n    print('hello')\n    try:\n        while True: pass\n"
            "    except Exception:\n        return []\n")
    ex = run(execute(code, P.function_name, P.visible[:1]))
    assert ex.tests["v1"].status == "timeout" and "hello" in ex.stdout


def test_runtime_error_reports_the_solution_line():
    ex = run(execute(RAISES, P.function_name, P.visible))
    assert ex.tests["v1"].error == {"type": "IndexError", "message": "list index out of range", "line": 2}


# ------------------------------------------------------------------ 2. judge

def test_good_and_slow_two_sum_differ_only_on_efficiency():
    good = run(final_report(Session("two-sum", "intermediate"), P, GOOD))
    slow = run(final_report(Session("two-sum", "intermediate"), P, SLOW))
    assert (good["breakdown"]["correctness"], good["breakdown"]["efficiency"]) == (50, 15)
    assert (slow["breakdown"]["correctness"], slow["breakdown"]["efficiency"]) == (50, 0)
    assert {k: (v["passed"], v["total"]) for k, v in slow["tiers"].items()} == {
        "visible": (3, 3), "hidden": (4, 4), "stress": (0, 2)}
    hidden = [g for g in grade(P, P.all_tests(), run(execute(GOOD, P.function_name, P.all_tests()))) if g.tier != "visible"]
    assert len(hidden) == 6 and all(g.args is None and g.expected is None and g.got is None for g in hidden)


def test_report_has_no_hidden_inputs_and_stub_gets_zero_quality():
    report = run(final_report(Session("two-sum", "beginner"), P, P.starter_code))
    assert report["breakdown"]["quality"] == 0 and report["breakdown"]["correctness"] == 0
    for tier in report["tiers"].values():
        assert all(set(c) == {"note", "status", "time_ms"} for c in tier["cases"])


def test_process_score():
    s = Session("two-sum", "beginner")
    s.hints = [hint(1), hint(2), hint(3), hint(4), hint(1, "inefficiency")]
    assert process_score(s) == 20 - (1 + 2 + 4 + 6)
    s.hints = []
    s.runs = [fail_run() for _ in range(6)]
    assert process_score(s) == 19            # 0.5 for each failed run beyond the 4th
    s.runs = [fail_run() for _ in range(40)]
    assert process_score(s) == 15            # capped at 5
    s.hints = [hint(4) for _ in range(5)]
    assert process_score(s) == 0


# ------------------------------------------------------------------ 4. helper policy

def test_idle_trigger_by_band():
    for level, quiet, expected in (("beginner", 50, True), ("beginner", 20, False),
                                   ("intermediate", 50, False), ("intermediate", 95, True),
                                   ("advanced", 9999, False)):
        s = Session("two-sum", level)
        s.last_activity = time.time() - quiet
        assert (helper.decide(s, "idle") is not None) == expected, (level, quiet)


def test_one_idle_hint_per_quiet_spell_and_cooldown():
    s = Session("two-sum", "beginner")
    s.last_activity = time.time() - 300
    s.hints.append(hint(1, "idle", age=100))          # past the 30s cooldown, same quiet spell
    assert helper.decide(s, "idle") is None
    s.hints = [hint(1, "request", sig="fail:v2,v3", age=5)]
    s.runs = [fail_run(), fail_run()]
    assert helper.decide(s, "fail_streak") is None    # cooling down
    assert helper.decide(s, "request").rung == 2      # explicit requests ignore it


def test_proactive_hints_stop_below_max_rung_and_reset_on_new_signature():
    s = Session("two-sum", "beginner")
    s.runs = [fail_run(), fail_run()]
    s.hints = [hint(3, "fail_streak", sig="fail:v2,v3", age=500)]
    assert helper.decide(s, "fail_streak").rung == 3  # beginner max is 4, proactive cap 3
    s.hints = [hint(1, "fail_streak", sig="fail:v2,v3", age=35)]
    assert helper.decide(s, "fail_streak").rung == 1  # not stuck for 40s yet
    s.runs += [fail_run("fail:v3"), fail_run("fail:v3")]
    s.hints = [hint(3, "fail_streak", sig="fail:v2,v3", age=500)]
    assert helper.decide(s, "fail_streak").rung == 1


def test_error_streak_and_inefficiency_by_band():
    for level, expected in (("beginner", True), ("advanced", False)):
        s = Session("two-sum", level)
        s.runs = [fail_run("err:IndexError:2", "IndexError") for _ in range(5)]
        assert (helper.decide(s, "error_streak") is not None) == expected
        assert (helper.decide(s, "inefficiency") is not None) == expected
    s = Session("two-sum", "beginner")
    s.inefficiency_flagged = True
    assert helper.decide(s, "inefficiency") is None


# ------------------------------------------------------------------ 5. generation fallbacks

def test_fallback_hints_work_offline_for_every_problem_and_rung():
    for p in PROBLEMS.values():
        s = Session(p.id, "beginner")
        for rung in (1, 2, 3, 4):
            for trigger in ("request", "idle", "fail_streak", "error_streak"):
                text = run(helper.generate(s, p, helper.HintDecision(trigger, rung), p.starter_code, None, None))
                assert p.hints[rung - 1] in text
        text = run(helper.generate(s, p, helper.HintDecision("inefficiency", 1), p.starter_code, None, None))
        for h in list(p.hints) + [text]:
            assert "hidden" not in h.lower() and "stress" not in h.lower() and "submit" not in h.lower()


def test_fallback_hint_leads_with_the_failing_example():
    s = Session("two-sum", "beginner")
    visible = grade(P, P.visible, run(execute(WRONG, P.function_name, P.visible)))
    text = run(helper.generate(s, P, helper.HintDecision("request", 1), WRONG, visible, None))
    assert text.startswith("Example v2 expected [1, 2] but got [0, 1].")
    syntax = analyze("def two_sum(:\n", "two_sum").syntax_error
    assert "Line 1" in run(helper.generate(s, P, helper.HintDecision("request", 1), "", None, syntax))


# ------------------------------------------------------------------ analysis + skill estimator

def test_structure_hash_ignores_whitespace_and_comments():
    base = analyze(GOOD, "two_sum")
    assert analyze(GOOD.replace("seen = {}", "seen = {}   # lookups\n"), "two_sum").structure_hash == base.structure_hash
    assert analyze(GOOD.replace("seen[x] = i", "seen[x] = i + 0"), "two_sum").structure_hash != base.structure_hash
    assert (base.max_loop_depth, analyze(SLOW, "two_sum").max_loop_depth) == (1, 2)
    assert analyze(P.starter_code, "two_sum").is_stub


def test_skill_estimator_priors_bands_and_clamp():
    assert [Session("two-sum", l).level_value for l in ("beginner", "intermediate", "advanced")] == [0.25, 0.55, 0.8]
    assert [band_for(v) for v in (0.39, 0.4, 0.69, 0.7)] == ["beginner", "intermediate", "intermediate", "advanced"]
    s = Session("two-sum", "intermediate")
    assert s.nudge_level(-0.2) is True and s.band == "beginner"
    s.nudge_level(-5)
    assert s.level_value == 0.05
    s.nudge_level(5)
    assert s.level_value == 0.95 and len(s.level_history) == 4


# ------------------------------------------------------------------ 3. engine + protocol

def until(ws, type_):
    seen = []
    while True:
        m = ws.receive_json()
        seen.append(m)
        if m["type"] == type_:
            return m, seen


def test_websocket_run_help_and_submit_lock():
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "run", "code": GOOD})
        assert ws.receive_json()["type"] == "error"              # no session yet
        ws.send_json({"type": "start", "problem_id": "two-sum", "level": "intermediate"})
        level, _ = until(ws, "level")
        assert (level["band"], level["value"], level["max_rung"]) == ("intermediate", 0.55, 3)

        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"              # the socket survives a bad frame
        ws.send_json({"type": "code", "code": "def two_sum(:\n"})
        assert until(ws, "analysis")[0]["syntax_error"]["line"] == 1

        ws.send_json({"type": "run", "code": WRONG})
        result, _ = until(ws, "run_result")
        assert [t["status"] for t in result["tests"]] == ["pass", "fail", "pass"] and "dbg" in result["stdout"]
        score, _ = until(ws, "live_score")
        assert (score["correctness"], score["process"]) == (33.3, 20.0)
        assert until(ws, "level")[0]["value"] == 0.59           # two newly passing examples

        ws.send_json({"type": "help", "code": WRONG, "message": "stuck"})
        h, seen = until(ws, "hint")
        assert (h["rung"], h["trigger"]) == (1, "request")
        assert {"type": "helper_status", "state": "thinking"} in seen
        assert until(ws, "live_score")[0]["process"] == 19.0

        ws.send_json({"type": "run", "code": SLOW})
        h, _ = until(ws, "hint")
        assert h["trigger"] == "inefficiency"
        assert until(ws, "live_score")[0]["process"] == 19.0    # the warning is free

        ws.send_json({"type": "submit", "code": SLOW})
        report = until(ws, "final_report")[0]["report"]
        assert report["breakdown"]["efficiency"] == 0 and report["breakdown"]["process"] == 19.0
        assert report["hints_used"] == [{"rung": 1, "trigger": "request"}, {"rung": 1, "trigger": "inefficiency"}]
        ws.send_json({"type": "run", "code": GOOD})
        assert until(ws, "error")[0]["message"].startswith("This session is already submitted")


def test_error_streak_hint_arrives_after_two_runs_for_a_beginner():
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "problem_id": "two-sum", "level": "beginner"})
        until(ws, "level")
        ws.send_json({"type": "run", "code": RAISES})
        _, seen = until(ws, "level")
        assert "hint" not in [m["type"] for m in seen]
        ws.send_json({"type": "run", "code": RAISES})
        assert until(ws, "hint")[0]["trigger"] == "error_streak"
