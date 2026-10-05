"""FastAPI entrypoint: serves the frontend, a small REST API, and the session WebSocket."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import config, skills
from .engine import Engine
from .llm import llm
from .problems import PROBLEMS
from .session import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

log = logging.getLogger("lcs")

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "index.html"

app = FastAPI(title="Live coding simulator")


@app.get("/")
async def index():
    return FileResponse(FRONTEND, headers={"Cache-Control": "no-cache"})   # never serve a stale UI


@app.get("/api/health")
async def health():
    return {"ok": True, "llm": llm.enabled, "provider": llm.provider if llm.enabled else None, "sandbox": config.SANDBOX,
            "helper_model": config.HELPER_MODEL, "judge_model": config.JUDGE_MODEL}


@app.get("/api/problems")
async def problems():
    return [p.summary() for p in PROBLEMS.values()]


@app.post("/api/profile")
async def profile(body: dict = Body(...)):
    """Skill graph data and recommended problems for a browser-held skill profile."""
    return skills.view(skills.clean(body.get("profile")), skills.clean_level(body.get("level")))


@app.get("/api/sessions/{session_id}")
async def session(session_id: str):
    data = await store.load_raw(session_id)
    if not data:
        raise HTTPException(404, "Session not found")
    return data


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    engine = Engine(ws)
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except (ValueError, KeyError):  # not JSON, or a binary frame
                msg = None
            if not isinstance(msg, dict):
                await engine.send("error", message="That message wasn't valid JSON. Send an object with a 'type'.")
                continue
            try:
                await engine.handle(msg)
            except Exception:
                log.exception("event '%s' failed", msg.get("type"))
                await engine.send("error", message="Something went wrong on the server. Try that again.")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("socket closed: %s", e)
    finally:
        engine.close()
