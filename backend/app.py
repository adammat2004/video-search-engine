"""FastAPI backend: search, media streaming and the DRES proxy.

Run:  .venv/bin/uvicorn backend.app:app --port 8000      (from the vbs/ directory)
Set VBS_NO_MODEL=1 to start without the SigLIP model (speech search and media only; used by tests).
"""
import io
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

from backend.dres import DresClient, DresError
from backend.engine import Engine, config

load_dotenv(config.ROOT / ".env")

S: dict = {}                     # app state: engine, dres client
LOCK = threading.Lock()          # one search at a time (MPS model + numpy buffers are shared)
LATENCY_LOG = config.LOGS / "latency.jsonl"
SUBMIT_LOG = config.LOGS / "submissions.jsonl"


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = time.time()
    S["engine"] = Engine(load_model=os.getenv("VBS_NO_MODEL") != "1")
    if S["engine"].model is not None:
        S["engine"].embed_text("warmup")
    S["dres"] = DresClient.from_env(log_path=SUBMIT_LOG)
    print(f"engine ready in {time.time() - t:.1f}s: {len(S['engine'].shots)} shots")
    if S["dres"].base_url and S["dres"].username:
        try:  # log in up front so the operator does not have to; the UI can retry
            S["dres"].login()
            print("DRES login ok")
        except Exception as ex:
            print(f"DRES login failed (retry from the UI): {ex}")
    yield


app = FastAPI(title="VBS retrieval", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def latency(request: Request, call_next):
    t = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/search"):
        ms = (time.perf_counter() - t) * 1000
        config.LOGS.mkdir(exist_ok=True)
        with open(LATENCY_LOG, "a") as f:
            f.write(json.dumps({"time": time.time(), "path": request.url.path,
                                "mode": getattr(request.state, "mode", None),
                                "status": response.status_code, "ms": round(ms, 2)}) + "\n")
        response.headers["X-Search-Ms"] = f"{ms:.1f}"
    return response


def engine() -> Engine:
    return S["engine"]


def need_model():
    if engine().model is None:
        raise HTTPException(503, "visual model not loaded (VBS_NO_MODEL=1)")


def respond(rows, scores, k, group_by_video, **extra):
    res = engine().results(rows, scores, group_by_video=group_by_video, k=k)
    return {"results": res, "count": len(res), **extra}


def depth(k, group_by_video):
    # grouping keeps one shot per video, so look deeper before grouping
    return min(len(engine().shots), k * 30 if group_by_video else k)


# ---------------------------------------------------------------------------- search
class TextQuery(BaseModel):
    q: str = Field(min_length=1)
    mode: Literal["visual", "speech", "fused"] = "fused"
    k: int = Field(200, ge=1, le=2000)
    group_by_video: bool = False


@app.post("/search/text")
def search_text(body: TextQuery, request: Request):
    request.state.mode = body.mode
    if body.mode != "speech":
        need_model()
    with LOCK:
        rows, scores = getattr(engine(), body.mode)(body.q, depth(body.k, body.group_by_video))
    return respond(rows, scores, body.k, body.group_by_video)


@app.post("/search/image")
def search_image(request: Request, file: UploadFile = File(...), k: int = Form(200),
                 group_by_video: bool = Form(False)):
    request.state.mode = "image"
    need_model()
    try:
        img = Image.open(io.BytesIO(file.file.read()))
    except Exception:
        raise HTTPException(400, "not an image")
    with LOCK:
        rows, scores = engine().image(img, depth(k, group_by_video))
    return respond(rows, scores, k, group_by_video)


@app.get("/search/similar/{shot_id}")
def search_similar(shot_id: str, request: Request, k: int = 200, group_by_video: bool = False):
    request.state.mode = "similar"
    if shot_id not in engine().row_of:
        raise HTTPException(404, "unknown shot")
    with LOCK:
        rows, scores = engine().similar(shot_id, depth(k, group_by_video))
    return respond(rows, scores, k, group_by_video)


class TemporalQuery(BaseModel):
    qa: str = Field(min_length=1)
    qb: str = Field(min_length=1)
    mode: Literal["visual", "speech"] = "visual"
    max_shots: int = Field(5, ge=1, le=50)
    max_seconds: float | None = Field(None, gt=0)
    k: int = Field(200, ge=1, le=2000)
    group_by_video: bool = False


@app.post("/search/temporal")
def search_temporal(body: TemporalQuery, request: Request):
    request.state.mode = "temporal"
    if body.mode == "visual":
        need_model()
    e = engine()
    with LOCK:
        rows, scores, rows_b = e.temporal(body.qa, body.qb, depth(body.k, body.group_by_video),
                                          body.max_shots, body.max_seconds, body.mode)
    out, seen = [], set()
    for r, s, b in zip(rows, scores, rows_b):
        if body.group_by_video:
            if e.vid[r] in seen:
                continue
            seen.add(e.vid[r])
        out.append(e.result(r, s, next_shot=e.result(b, 0.0)))
        if len(out) >= body.k:
            break
    return {"results": out, "count": len(out)}


class Feedback(BaseModel):
    positives: list[str] = []
    negatives: list[str] = []
    q: str | None = None
    k: int = Field(200, ge=1, le=2000)
    group_by_video: bool = False


@app.post("/search/feedback")
def search_feedback(body: Feedback, request: Request):
    request.state.mode = "feedback"
    if body.q:
        need_model()
    unknown = [s for s in body.positives + body.negatives if s not in engine().row_of]
    if unknown or not (body.positives or body.q):
        raise HTTPException(400, f"need positives or q; unknown shots: {unknown}")
    with LOCK:
        rows, scores = engine().feedback(body.positives, body.negatives, body.q,
                                         depth(body.k, body.group_by_video))
    return respond(rows, scores, body.k, body.group_by_video)


# ---------------------------------------------------------------------------- media
@app.get("/video/{v3c_id}/shots")
def video_shots(v3c_id: str):
    e = engine()
    if v3c_id not in e.video_rows:
        raise HTTPException(404, "unknown video")
    a, b = e.video_rows[v3c_id]
    v = e.videos.loc[v3c_id]
    return {"v3c_id": v3c_id, "title": v.title, "duration_ms": int(v.duration_s * 1000),
            "vimeo_url": v.vimeo_url, "shots": [e.result(r, 0.0) for r in range(a, b)]}


@app.get("/thumb/{shot_id}")
def thumb(shot_id: str):
    e = engine()
    if shot_id not in e.row_of:
        raise HTTPException(404, "unknown shot")
    return FileResponse(config.THUMBS / e.shots.thumb_path.iat[e.row_of[shot_id]], media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800, immutable"})


CHUNK = 1 << 20


def _file_chunks(path: Path, start: int, length: int):
    with open(path, "rb") as f:
        f.seek(start)
        while length > 0:
            data = f.read(min(CHUNK, length))
            if not data:
                break
            length -= len(data)
            yield data


@app.get("/video/{v3c_id}.mp4")
def video(v3c_id: str, request: Request):
    """Serve the 480p mp4 with HTTP Range support (needed for seeking in <video>)."""
    if not v3c_id.isdigit():
        raise HTTPException(404)
    path = config.VIDEOS / f"{v3c_id}.mp4"
    if not path.exists():
        raise HTTPException(404, "video not downloaded")
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Content-Type": "video/mp4", "Cache-Control": "public, max-age=86400"}
    rng = request.headers.get("range")
    if not rng:
        return StreamingResponse(_file_chunks(path, 0, size), headers={**headers, "Content-Length": str(size)})
    try:
        unit, spec = rng.split("=", 1)
        first = spec.split(",")[0].strip()         # multi-range requests: serve the first range only
        a, b = first.split("-", 1)
        if unit.strip() != "bytes":
            raise ValueError
        if a == "":                                 # suffix range: last N bytes
            start, end = max(0, size - int(b)), size - 1
        else:
            start, end = int(a), (int(b) if b else size - 1)
        end = min(end, size - 1)
        if start > end or start >= size:
            raise ValueError
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1
    return StreamingResponse(_file_chunks(path, start, length), status_code=206,
                             headers={**headers, "Content-Length": str(length),
                                      "Content-Range": f"bytes {start}-{end}/{size}"})


# ---------------------------------------------------------------------------- DRES proxy
def dres() -> DresClient:
    d = S["dres"]
    if not d.base_url:
        raise HTTPException(503, "DRES_URL not configured in .env")
    return d


def dres_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except DresError as ex:
        raise HTTPException(502, f"DRES: {ex.description}")
    except Exception as ex:  # network errors etc.
        raise HTTPException(502, f"DRES unreachable: {ex}")


class Login(BaseModel):
    username: str | None = None
    password: str | None = None


@app.post("/dres/login")
def dres_login(body: Login | None = None):
    body = body or Login()
    u = dres_call(dres().login, body.username, body.password)
    return {"username": u.get("username"), "role": u.get("role"), "logged_in": True}


@app.get("/dres/status")
def dres_status():
    d = S["dres"]
    out = {"configured": bool(d.base_url), "url": d.base_url, "api": d.api, "logged_in": d.session is not None,
           "media_name_example": d.media_name("00031")}
    if d.base_url and d.session:
        try:
            evs = d.evaluations()
            active = [e for e in evs if e.get("status") == "ACTIVE"]
            out.update(evaluations=len(evs), active=[{"id": e["id"], "name": e["name"]} for e in active])
            if len(active) == 1:
                out["current_task"] = d.current_task(active[0]["id"])
        except Exception as ex:
            out["error"] = str(ex)
    return out


@app.get("/dres/evaluations")
def dres_evaluations():
    return dres_call(dres().evaluations)


class Answer(BaseModel):
    shot_id: str | None = None
    v3c_id: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


class Submit(BaseModel):
    evaluation_id: str | None = None
    answers: list[Answer] = Field(min_length=1, max_length=100)


@app.post("/dres/submit")
def dres_submit(body: Submit):
    """Submit one or more segments (one DRES submission each, so every segment gets its own verdict).

    An answer is a shot_id (official msb boundaries) and/or explicit v3c_id + start_ms/end_ms.
    """
    d, e = dres(), engine()
    eval_id = body.evaluation_id
    if not eval_id and d.api != "legacy":
        ev = dres_call(d.active_evaluation)
        if not ev:
            raise HTTPException(409, "no single ACTIVE evaluation; pass evaluation_id")
        eval_id = ev["id"]
    out = []
    for a in body.answers:
        row = e.row_of.get(a.shot_id) if a.shot_id else None
        if a.shot_id and row is None:
            raise HTTPException(400, f"unknown shot {a.shot_id}")
        v3c = a.v3c_id or e.vid[row]
        if v3c not in e.video_rows:
            raise HTTPException(400, f"unknown video {v3c}")
        start = a.start_ms if a.start_ms is not None else int(e.start_ms[row])
        end = a.end_ms if a.end_ms is not None else int(e.end_ms[row])
        dur = int(e.videos.at[v3c, "duration_s"] * 1000)
        start = max(0, start)
        end = max(end, start + config.MIN_SHOT_MS)    # degenerate (zero-length) shots
        if dur:
            end = min(end, max(dur, start + config.MIN_SHOT_MS))
        mid = None
        if row is not None:
            mid = int((e.shots.start_frame.iat[row] + e.shots.end_frame.iat[row]) // 2)
        res = dres_call(d.submit, eval_id, v3c, start, end, mid)
        out.append({**res, "shot_id": a.shot_id})
    return {"results": out}


@app.get("/dres/log")
def dres_log(limit: int = 200):
    if not SUBMIT_LOG.exists():
        return []
    lines = SUBMIT_LOG.read_text().splitlines()[-limit:]
    return [json.loads(x) for x in reversed(lines)]
