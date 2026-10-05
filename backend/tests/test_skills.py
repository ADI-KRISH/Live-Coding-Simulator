"""Per-topic skills, recommendations, measured complexity and step-through tracing."""
import asyncio

from fastapi.testclient import TestClient

from app import skills
from app.judge import final_report, measure_complexity
from app.main import app
from app.problems import PROBLEMS
from app.sandbox import execute
from app.session import LEVEL_PRIORS, Session, band_for

from .test_core import GOOD, SLOW, P
from .test_milestones import until

BSEARCH = PROBLEMS["binary-search"]
LINEAR_SCAN = ("def binary_search(nums, target):\n    for i, x in enumerate(nums):\n"
               "        if x == target:\n            return i\n    return -1\n")
HALVING = ("def binary_search(nums, target):\n    lo, hi = 0, len(nums) - 1\n    while lo <= hi:\n"
           "        mid = (lo + hi) // 2\n        if nums[mid] == target:\n            return mid\n"
           "        if nums[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n"
           "    return -1\n")


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ problem bank

def test_every_level_and_topic_has_problems():
    by_level = {level: [p for p in PROBLEMS.values() if p.difficulty == level] for level in LEVEL_PRIORS}
    assert all(len(ps) >= 4 for ps in by_level.values())
    used = {t for p in PROBLEMS.values() for t in p.topics}
    assert used == set(skills.TOPICS)
    for p in PROBLEMS.values():
        assert p.topics and p.scale is not None
        p.reference(*p.scale(500))            # the generator builds a valid input


# ------------------------------------------------------------------ skill profile

def test_untrusted_profile_is_cleaned():
    dirty = {"skills": {"arrays": 7, "hashmaps": "high", "nope": 0.5, "dp": float("nan"), "graphs": 0.3},
             "solved": ["two-sum", "<script>", 4]}
    assert skills.clean(dirty) == {"skills": {"arrays": 0.95, "graphs": 0.3}, "solved": ["two-sum"]}
    assert skills.clean("garbage") == {"skills": {}, "solved": []}
    assert skills.clean_level("wizard") == "intermediate"


def test_session_starts_at_the_topic_skill_not_the_declared_level():
    profile = skills.clean({"skills": {"arrays": 0.85, "hashmaps": 0.8, "dp": 0.2}})
    two_sum, coins, islands = PROBLEMS["two-sum"], PROBLEMS["coin-change"], PROBLEMS["number-of-islands"]
    assert band_for(skills.start_level(profile, two_sum, "intermediate")) == "advanced"     # strong: fewer hints
    assert band_for(skills.start_level(profile, coins, "intermediate")) == "beginner"       # weak: more hints
    assert skills.start_level(profile, islands, "intermediate") == LEVEL_PRIORS["intermediate"]   # never practised


def test_score_moves_only_the_problems_topics_and_in_one_direction():
    profile = skills.clean(None)
    changes = skills.update(profile, PROBLEMS["two-sum"], 95, "beginner")
    assert set(changes) == {"arrays", "hashmaps"} and profile["solved"] == ["two-sum"]
    assert all(c["after"] > c["before"] == 0.25 for c in changes.values())

    expert = skills.clean({"skills": {"arrays": 0.9, "hashmaps": 0.9}})
    skills.update(expert, PROBLEMS["two-sum"], 100, "advanced")
    assert expert["skills"]["arrays"] == 0.9                 # acing an easy problem never lowers skill
    skills.update(expert, PROBLEMS["two-sum"], 20, "advanced")
    assert expert["skills"]["arrays"] < 0.9                  # failing it does

    novice = skills.clean({"skills": {"graphs": 0.1}})
    skills.update(novice, PROBLEMS["course-schedule"], 40, "beginner")
    assert novice["skills"]["graphs"] == 0.1 and novice["solved"] == []   # failing a hard one never raises


def test_recommendations_follow_each_topics_skill():
    fresh = skills.recommend(skills.clean(None), "beginner")
    assert len(fresh) == 3 and all(r["difficulty"] == "beginner" for r in fresh)

    profile = skills.clean({"skills": {"graphs": 0.85}, "solved": ["number-of-islands"]})
    recs = skills.recommend(profile, "beginner", k=len(PROBLEMS))
    by_id = {r["id"]: i for i, r in enumerate(recs)}
    assert recs[-1]["id"] == "number-of-islands"                       # solved problems go last
    assert by_id["course-schedule"] < by_id["longest-increasing-subsequence"]   # advanced graphs before advanced dp
    assert "graphs" in recs[by_id["course-schedule"]]["reason"]

    view = skills.view(profile, "beginner")
    graphs = next(t for t in view["topics"] if t["id"] == "graphs")
    assert (graphs["band"], graphs["practised"]) == ("advanced", True) and len(view["topics"]) == len(skills.TOPICS)


def test_profile_endpoint_and_start_with_profile():
    client = TestClient(app)
    body = client.post("/api/profile", json={"profile": {"skills": {"dp": 0.9}}, "level": "beginner"}).json()
    assert next(t for t in body["topics"] if t["id"] == "dp")["value"] == 0.9
    assert {"difficulty", "topics"} <= set(client.get("/api/problems").json()[0])

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "problem_id": "coin-change", "level": "beginner",
                      "profile": {"skills": {"dp": 0.9}}})
        level, _ = until(ws, "level")
        assert (level["band"], level["declared"], level["max_rung"]) == ("advanced", "beginner", 2)
        ws.send_json({"type": "submit", "code": "def coin_change(coins, amount):\n    return -1\n"})
        report = until(ws, "final_report")[0]["report"]
        assert report["skill_changes"]["dp"]["after"] < 0.9 == report["skill_changes"]["dp"]["before"]
        assert report["profile"]["skills"]["dp"] == report["skill_changes"]["dp"]["after"]
        assert len(report["skills"]["recommendations"]) == 3


# ------------------------------------------------------------------ measured complexity

def test_measured_complexity_separates_linear_from_quadratic():
    good, slow = run(measure_complexity(P, GOOD)), run(measure_complexity(P, SLOW))
    assert good["matches_optimal"] and good["label"] == "O(n) or O(n log n)" and len(good["points"]) == 8
    assert not slow["matches_optimal"] and slow["label"] == "O(n^2)" and slow["timed_out_at"]


def test_linear_scan_passes_binary_search_tests_but_loses_efficiency():
    fast = run(final_report(Session("binary-search", "beginner"), BSEARCH, HALVING))
    scan = run(final_report(Session("binary-search", "beginner"), BSEARCH, LINEAR_SCAN))
    assert fast["measured_complexity"]["label"] == "O(log n) or better" and fast["breakdown"]["efficiency"] == 15
    assert scan["tiers"]["stress"]["passed"] == 2 and scan["breakdown"]["correctness"] == 50
    assert scan["measured_complexity"]["matches_optimal"] is False and scan["breakdown"]["efficiency"] == 10
    assert "measured" in scan["complexity"]


def test_reference_solutions_match_their_optimal_complexity():
    import inspect
    for p in PROBLEMS.values():
        src = inspect.getsource(p.reference).replace(p.reference.__name__, p.function_name, 1)
        m = run(measure_complexity(p, src))
        assert m and m["matches_optimal"], (p.id, m)


# ------------------------------------------------------------------ step-through

def test_trace_records_lines_locals_and_return():
    ex = run(execute(GOOD, P.function_name, P.visible[:1], trace=400))
    steps = ex.trace["steps"]
    assert steps[0]["line"] == 2 and steps[0]["locals"] == {"nums": "[2, 7, 11, 15]", "target": "9"}
    assert steps[-1]["event"] == "return" and steps[-1]["returned"] == "[0, 1]"
    assert steps[-1]["locals"]["seen"] == "{2: 0}" and steps[-1]["stack"] == ["two_sum"]
    assert ex.tests["v1"].got == [0, 1]


def test_trace_stops_at_the_step_limit_and_keeps_prints():
    loop = "def two_sum(nums, target):\n    print('hi')\n    while True:\n        target += 1\n"
    ex = run(execute(loop, P.function_name, P.visible[:1], trace=50))
    assert ex.tests["v1"].status == "stopped" and len(ex.trace["steps"]) == 50
    assert ex.trace["stdout"] == "hi\n" and ex.trace["steps"][0]["out"] == 0 and ex.trace["steps"][-1]["out"] == 3


def test_websocket_trace_event_is_free_and_works_after_submit():
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"type": "start", "problem_id": "two-sum", "level": "intermediate"})
        until(ws, "level")
        ws.send_json({"type": "trace", "code": GOOD, "test_id": "v2"})
        t = until(ws, "trace_result")[0]
        assert (t["test_id"], t["status"], t["truncated"]) == ("v2", "pass", False) and t["steps"]
        ws.send_json({"type": "trace", "code": "def two_sum(:\n"})
        assert until(ws, "trace_result")[0]["load_error"]["type"] == "SyntaxError"
        ws.send_json({"type": "submit", "code": GOOD})
        report = until(ws, "final_report")[0]["report"]
        assert report["runs"] == 0 and report["breakdown"]["process"] == 20
        ws.send_json({"type": "trace", "code": GOOD})
        assert until(ws, "trace_result")[0]["test_id"] == "v1"
