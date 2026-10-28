"""DRES client, written against the official DRES OpenAPI client spec (docs/dres/oas-client.json,
DRES 2.0.x) and the legacy spec (docs/dres/legacy.oas.json).

v2 flow:
  POST /api/v2/login                          {username, password} -> ApiUser{sessionId}
  GET  /api/v2/client/evaluation/list?session  -> [ApiClientEvaluationInfo{id, name, status, ...}]
  GET  /api/v2/client/evaluation/currentTask/{evaluationId}?session -> ApiClientTaskTemplateInfo
  POST /api/v2/submit/{evaluationId}?session  ApiClientSubmission
       {"answerSets": [{"answers": [{"mediaItemName", "start", "end"}]}]}   (start/end in ms)
       -> 200/202 SuccessfulSubmissionsStatus{status, submission: CORRECT|WRONG|INDETERMINATE|UNDECIDABLE,
          description}; 400/401/404/412 ErrorStatus{status, description}
Legacy fallback (DRES_API=legacy):
  GET  /api/v2/submit?item=<name>&frame=<n>&session=   (a single point, so we send the shot's middle frame)

Every request and response of a submission is appended to logs/submissions.jsonl.
"""
import json
import os
import threading
import time
from pathlib import Path

import httpx

VERDICTS = {"CORRECT", "WRONG", "INDETERMINATE", "UNDECIDABLE"}


class DresError(Exception):
    def __init__(self, status_code: int, description: str):
        super().__init__(f"DRES {status_code}: {description}")
        self.status_code, self.description = status_code, description


class DresClient:
    def __init__(self, base_url: str, username: str = "", password: str = "", api: str = "v2",
                 media_name_fmt: str = "{v3c_id}", log_path: Path | None = None,
                 http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.username, self.password = username, password
        self.api = api
        self.media_name_fmt = media_name_fmt
        self.log_path = log_path
        self.http = http or httpx.Client(base_url=self.base_url, timeout=10.0)
        self.session: str | None = None
        self.user: dict | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, log_path: Path | None = None):
        return cls(os.getenv("DRES_URL", ""), os.getenv("DRES_USER", ""), os.getenv("DRES_PASS", ""),
                   os.getenv("DRES_API", "v2"), os.getenv("MEDIA_NAME_FMT", "{v3c_id}"), log_path)

    # ------------------------------------------------------------------ plumbing
    def _log(self, rec: dict):
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}) + "\n")

    @staticmethod
    def _json(r: httpx.Response):
        try:
            return r.json()
        except ValueError:
            return {"description": r.text}

    def _request(self, method: str, path: str, *, retry_login=True, **kw) -> httpx.Response:
        if self.session is None:
            self.login()
        params = {**kw.pop("params", {}), "session": self.session}
        r = self.http.request(method, path, params=params, **kw)
        if r.status_code == 401 and retry_login:
            self.login()
            return self._request(method, path, retry_login=False, params=params, **kw)
        return r

    # ------------------------------------------------------------------ API
    def login(self, username: str | None = None, password: str | None = None) -> dict:
        with self._lock:
            self.username = username or self.username
            self.password = password or self.password
            r = self.http.post("/api/v2/login", json={"username": self.username, "password": self.password})
            body = self._json(r)
            if r.status_code != 200:
                self.session = None
                raise DresError(r.status_code, body.get("description", r.text))
            self.user, self.session = body, body["sessionId"]
            return body

    def evaluations(self) -> list[dict]:
        r = self._request("GET", "/api/v2/client/evaluation/list")
        if r.status_code != 200:
            raise DresError(r.status_code, self._json(r).get("description", r.text))
        return r.json()

    def active_evaluation(self) -> dict | None:
        active = [e for e in self.evaluations() if e.get("status") == "ACTIVE"]
        return active[0] if len(active) == 1 else None

    def current_task(self, evaluation_id: str) -> dict | None:
        r = self._request("GET", f"/api/v2/client/evaluation/currentTask/{evaluation_id}")
        return r.json() if r.status_code == 200 else None

    def media_name(self, v3c_id: str) -> str:
        return self.media_name_fmt.format(v3c_id=v3c_id)

    def submit(self, evaluation_id: str, v3c_id: str, start_ms: int, end_ms: int,
               mid_frame: int | None = None) -> dict:
        """Submit one segment. Returns {verdict, http_status, description, request}."""
        name = self.media_name(v3c_id)
        if self.api == "legacy":
            req = {"item": name, "frame": mid_frame}
            r = self._request("GET", "/api/v2/submit", params=req)
        else:
            req = {"answerSets": [{"answers": [{"mediaItemName": name, "start": int(start_ms), "end": int(end_ms)}]}]}
            r = self._request("POST", f"/api/v2/submit/{evaluation_id}", json=req)
        body = self._json(r)
        verdict = body.get("submission") if r.status_code in (200, 202) else None
        out = {"verdict": verdict if verdict in VERDICTS else ("ERROR" if r.status_code >= 400 else verdict),
               "http_status": r.status_code, "description": body.get("description", ""),
               "evaluation_id": evaluation_id, "v3c_id": v3c_id, "start_ms": int(start_ms),
               "end_ms": int(end_ms), "api": self.api, "request": req}
        self._log({"event": "submit", **out, "response": body})
        return out
