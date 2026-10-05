"""Per-connection session engine.

Client -> server events
  start   {problem_id, level, profile?}   profile = per-topic skills kept by the browser
  code    {code}                debounced snapshot while typing
  run     {code}                run visible examples
  trace   {code, test_id?}      step through one visible example line by line
  help    {code, message?}      explicit hint request
  submit  {code}                final judging

Server -> client events
  session, analysis, run_result, trace_result, live_score, level, hint, helper_status,
  final_report, error
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket

from . import config, helper, skills
from .analysis import CodeAnalysis, analyze
from .judge import GradedTest, final_report, grade, live_score
from .problems import Problem, get_problem
from .sandbox import execute
from .session import HintRecord, RunRecord, Session, band_for, store

log = logging.getLogger("lcs.engine")
MAX_CODE = 20000
TRACE_STEPS = 400     # step-through stops recording after this many executed lines


class Engine:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.session: Session | None = None
        self.problem: Problem | None = None
        self.analysis: CodeAnalysis | None = None
        self.last_visible: list[GradedTest] | None = None
        self.profile: dict = skills.clean(None)
        self.lock = asyncio.Lock()
        self.idle_task: asyncio.Task | None = None
        self.hint_task: asyncio.Task | None = None
        self.closed = False

    # ------------------------------------------------------------ plumbing
    async def send(self, type_: str, **data) -> None:
        if self.closed:
            return
        try:
            await self.ws.send_json({"type": type_, **data})
        except Exception:
            self.closed = True

    def close(self) -> None:
        self.closed = True
        for t in (self.idle_task, self.hint_task):
            if t and not t.done():
                t.cancel()

    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "start":
            async with self.lock:
                await self._start(msg)
            return
        if not self.session:
            await self.send("error", message="Start a session first.")
            return
        async with self.lock:
            if kind == "code":
                self._update_code(msg.get("code", ""))
                await self._send_analysis()
            elif kind == "run":
                await self._run(msg.get("code", self.session.code))
            elif kind == "trace":
                await self._trace(msg.get("code", self.session.code), msg.get("test_id"))
            elif kind == "help":
                self._update_code(msg.get("code", self.session.code))
                await self._help(str(msg.get("message", ""))[:500])
            elif kind == "submit":
                await self._submit(msg.get("code", self.session.code))
            else:
                await self.send("error", message=f"Unknown event '{kind}'.")
        await store.save(self.session)

    # ------------------------------------------------------------ events
    async def _start(self, msg: dict) -> None:
        problem = get_problem(msg.get("problem_id", ""))
        if not problem:
            await self.send("error", message="Unknown problem.")
            return
        level = skills.clean_level(msg.get("level"))
        self.close()
        self.closed = False
        self.problem = problem
        self.profile = skills.clean(msg.get("profile"))
        self.session = Session(problem_id=problem.id, declared_level=level, code=problem.starter_code)
        # hints follow the coder's skill in this problem's topics, not just the declared level
        self.session.topic_levels = {t: skills.topic_skill(self.profile, t, level) for t in problem.topics}
        self.session.start_at(skills.start_level(self.profile, problem, level))
        self.last_visible = None
        self.analysis = analyze(self.session.code, problem.function_name)
        self.session.last_structure = self.analysis.structure_hash
        await store.save(self.session)
        await self.send("session", session_id=self.session.id, problem=problem.public(),
                        started_at=self.session.started_at)
        await self._send_level(changed=False)
        self.idle_task = asyncio.create_task(self._idle_loop())

    def _update_code(self, code: str) -> None:
        s = self.session
        code = (code if isinstance(code, str) else "")[:MAX_CODE]
        s.code = code
        self.analysis = analyze(code, self.problem.function_name)
        if self.analysis.structure_hash != s.last_structure:
            s.last_structure = self.analysis.structure_hash
            s.last_activity = time.time()

    async def _send_analysis(self) -> None:
        a = self.analysis
        await self.send("analysis", syntax_error=a.syntax_error, has_function=a.has_function,
                        max_loop_depth=a.max_loop_depth)

    async def _run(self, code: str) -> None:
        s, p = self.session, self.problem
        if s.submitted:
            await self.send("error", message="This session is already submitted. Start a new one.")
            return
        self._update_code(code)
        s.last_activity = time.time()
        a = self.analysis
        prev = s.last_run()
        total = len(p.visible)
        delta = 0.0

        if a.syntax_error:
            se = a.syntax_error
            rec = RunRecord(time.time(), 0, total, [t.id for t in p.visible], "SyntaxError",
                            f"err:SyntaxError:{se.get('line')}")
            graded: list[GradedTest] = []
            await self.send("run_result", tests=[], load_error=se, stdout="", crashed=None)
            delta -= 0.01
        else:
            await self.send("run_status", state="running")
            ex = await execute(s.code, p.function_name, p.visible)
            if ex.crashed and not ex.tests:
                await self.send("run_result", tests=[], load_error=None, stdout=ex.stdout, crashed=ex.crashed)
                return
            graded = grade(p, p.visible, ex)
            passed = sum(g.status == "pass" for g in graded)
            failing = [g.id for g in graded if g.status != "pass"]
            err = ex.load_error or next((g.error for g in graded if g.error), None)
            err_type = err.get("type") if err else None
            if err_type:
                sig = f"err:{err_type}:{err.get('line')}"
            elif failing:
                sig = "fail:" + ",".join(failing)
            else:
                sig = "pass"
            rec = RunRecord(time.time(), passed, total, failing, err_type, sig)

            if passed > s.best_visible_passed:
                delta += 0.02 * min(3, passed - s.best_visible_passed)
                s.best_visible_passed = passed
            if passed == total and s.first_full_pass_at is None:
                s.first_full_pass_at = time.time()
                if not s.fast_bonus_given and s.elapsed < p.expected_minutes * 60 * 0.5 and not s.hints:
                    delta += 0.05
                    s.fast_bonus_given = True
            await self.send("run_result", tests=[g.to_dict() for g in graded],
                            load_error=ex.load_error, stdout=ex.stdout, crashed=ex.crashed)

        if prev and rec.error_type and prev.error_type == rec.error_type:
            delta -= 0.02
        elif prev and rec.failing and prev.signature == rec.signature:
            delta -= 0.01

        s.runs.append(rec)
        self.last_visible = graded or None
        changed = s.nudge_level(delta) if delta else False
        await self.send("live_score", **live_score(s, graded))
        await self._send_level(changed)

        if rec.error_type:
            await self._maybe_hint("error_streak")
        elif rec.failing:
            await self._maybe_hint("fail_streak")
        elif a.max_loop_depth >= 2 and not p.nested_ok and p.optimal_complexity in ("O(n)", "O(n log n)"):
            await self._maybe_hint("inefficiency")

    async def _trace(self, code: str, test_id) -> None:
        """Step-through: run one visible example under a tracer. Free; it never affects the score."""
        s, p = self.session, self.problem
        code = (code if isinstance(code, str) else "")[:MAX_CODE]
        if not s.submitted:
            s.last_activity = time.time()
        test = next((t for t in p.visible if t.id == test_id), p.visible[0])
        syntax = analyze(code, p.function_name).syntax_error
        if syntax:
            await self.send("trace_result", test_id=test.id, steps=[], load_error=syntax)
            return
        await self.send("run_status", state="tracing")
        ex = await execute(code, p.function_name, [test], trace=TRACE_STEPS)
        g = grade(p, [test], ex)[0]
        raw = ex.tests.get(test.id)
        trace = ex.trace or {"steps": [], "stdout": ""}
        await self.send("trace_result", test_id=test.id, args=test.args, expected=test.expected, got=g.got,
                        status=g.status, error=g.error, load_error=ex.load_error, crashed=ex.crashed,
                        steps=trace["steps"], stdout=trace["stdout"],
                        truncated=bool(raw and raw.status == "stopped"))
    async def _help(self, message: str) -> None:
        if self.session.submitted:
            return
        changed = self.session.nudge_level(-0.03)
        await self._send_level(changed)
        await self._maybe_hint("request", message)

    async def _submit(self, code: str) -> None:
        s, p = self.session, self.problem
        if s.submitted:
            await self.send("final_report", report=s.final_report)
            return
        self._update_code(code)
        await self.send("run_status", state="judging")
        report = await final_report(s, p, s.code)
        # the judged score moves the coder's skill in this problem's topics
        report["skill_changes"] = skills.update(self.profile, p, report["total"], s.declared_level)
        report["profile"] = self.profile
        report["skills"] = skills.view(self.profile, s.declared_level)
        s.submitted = True
        s.final_report = report
        self.close()
        self.closed = False
        await self.send("final_report", report=report)

    # ------------------------------------------------------------ helper
    async def _maybe_hint(self, trigger: str, message: str = "") -> None:
        if self.hint_task and not self.hint_task.done():
            if trigger == "request":
                await self.send("helper_status", state="busy")
            return
        decision = helper.decide(self.session, trigger)
        if decision is None:
            if trigger == "request":
                await self.send("helper_status", state="idle")
            return
        if decision.trigger == "inefficiency":
            self.session.inefficiency_flagged = True
        await self.send("helper_status", state="thinking")
        self.hint_task = asyncio.create_task(self._deliver_hint(decision, message))

    async def _deliver_hint(self, decision: helper.HintDecision, message: str) -> None:
        s, p = self.session, self.problem
        signature = s.current_signature()
        try:
            text = await helper.generate(s, p, decision, s.code, self.last_visible,
                                         self.analysis.syntax_error if self.analysis else None, message)
        except Exception as e:
            log.exception("hint generation failed: %s", e)
            text = p.hints[decision.rung - 1]
        if s.submitted or self.closed:
            return
        s.hints.append(HintRecord(time.time(), decision.rung, decision.trigger, text, signature))
        await self.send("hint", rung=decision.rung, rung_name=helper.RUNG_NAMES[decision.rung],
                        trigger=decision.trigger, trigger_label=helper.TRIGGER_LABELS[decision.trigger],
                        text=text, band=s.band, at=time.time())
        await self.send("helper_status", state="idle")
        await self.send("live_score", **live_score(s, self.last_visible or []))
        await store.save(s)

    async def _idle_loop(self) -> None:
        try:
            while not self.closed and self.session and not self.session.submitted:
                await asyncio.sleep(config.IDLE_CHECK_SECONDS)
                async with self.lock:
                    await self._maybe_hint("idle")
        except asyncio.CancelledError:
            pass

    async def _send_level(self, changed: bool) -> None:
        s = self.session
        pol = helper.POLICY[s.band]
        await self.send("level", value=round(s.level_value, 3), band=s.band, declared=s.declared_level,
                        changed=changed, max_rung=pol["max_rung"], proactive_idle=pol["idle"])
