"""A minimal fake DRES server implementing the v2 client routes we use (per docs/dres/oas-client.json)
plus the legacy GET submit. For tests and for UI practice before the course server is available.

Run:   .venv/bin/uvicorn scripts.fake_dres:app --port 8081
Then:  DRES_URL=http://127.0.0.1:8081  DRES_USER=team  DRES_PASS=secret  in .env

The target is set with FAKE_TARGET="<mediaItemName>:<start_ms>-<end_ms>" (default 00031:3586-8008).
A submission is CORRECT if the item matches and the submitted range overlaps the target range.
"""
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="fake DRES")
USERS = {"team": "secret"}
SESSIONS: set[str] = set()
EVAL = {"id": "eval-1", "name": "Practice run", "type": "SYNCHRONOUS", "status": "ACTIVE",
        "templateId": "tpl-1", "templateDescription": "fake", "teams": ["team"],
        "taskTemplates": [{"name": "kis-1", "taskGroup": "KIS-V", "taskType": "KIS", "duration": 300}]}
SUBMISSIONS: list[dict] = []


def target():
    item, rng = os.getenv("FAKE_TARGET", "00031:3586-8008").split(":")
    a, b = rng.split("-")
    return item, int(a), int(b)


def err(code, msg):
    return JSONResponse({"status": False, "description": msg}, status_code=code)


def check(session):
    if session not in SESSIONS:
        raise HTTPException(401)


@app.exception_handler(HTTPException)
def http_exc(_, exc: HTTPException):
    return err(exc.status_code, "Unauthorized" if exc.status_code == 401 else str(exc.detail))


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/v2/login")
def login(body: LoginRequest):
    if USERS.get(body.username) != body.password:
        return err(401, "Invalid credentials")
    sid = uuid.uuid4().hex
    SESSIONS.add(sid)
    return {"id": "u1", "username": body.username, "role": "PARTICIPANT", "sessionId": sid}


@app.get("/api/v2/client/evaluation/list")
def evaluations(session: str = ""):
    check(session)
    return [EVAL]


@app.get("/api/v2/client/evaluation/currentTask/{evaluation_id}")
def current_task(evaluation_id: str, session: str = ""):
    check(session)
    return EVAL["taskTemplates"][0]


def judge(item, start, end):
    t_item, t_start, t_end = target()
    if start is not None and end is not None and end < start:
        return None
    ok = item == t_item and (start is None or (start <= t_end and (end or start) >= t_start))
    return "CORRECT" if ok else "WRONG"


@app.post("/api/v2/submit/{evaluation_id}")
def submit(evaluation_id: str, body: dict, session: str = ""):
    check(session)
    if evaluation_id != EVAL["id"]:
        return err(404, "Evaluation not found")
    try:
        ans = body["answerSets"][0]["answers"][0]
        item, start, end = ans["mediaItemName"], ans.get("start"), ans.get("end")
    except (KeyError, IndexError, TypeError):
        return err(400, "Invalid submission")
    verdict = judge(item, start, end)
    if verdict is None:
        return err(400, "end before start")
    SUBMISSIONS.append({"item": item, "start": start, "end": end, "verdict": verdict})
    return {"status": True, "submission": verdict, "description": f"Submission {verdict.lower()}"}


@app.get("/api/v2/submit")
def legacy_submit(item: str, frame: int | None = None, session: str = ""):
    check(session)
    verdict = "CORRECT" if item == target()[0] else "WRONG"
    SUBMISSIONS.append({"item": item, "frame": frame, "verdict": verdict})
    return {"status": True, "submission": verdict, "description": f"Submission {verdict.lower()}"}
