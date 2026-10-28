"""Smoke tests for every backend endpoint and the DRES client (against scripts/fake_dres.py).

Run from vbs/:  .venv/bin/pytest -q backend/tests
Needs the index built by indexer/run_all.sh. Loads the SigLIP model once (~15 s).
"""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import app as appmod
from backend.dres import DresClient, DresError
from backend.engine import config
from scripts import fake_dres


@pytest.fixture(scope="module")
def client():
    with TestClient(appmod.app) as c:
        yield c


@pytest.fixture(scope="module")
def some_shot(client):
    e = appmod.S["engine"]
    return e.shots.iloc[len(e.shots) // 2]


def fake_dres_client(tmp_path, api="v2"):
    http = TestClient(fake_dres.app)  # an httpx.Client bound to the fake server
    return DresClient("http://testserver", "team", "secret", api=api, log_path=tmp_path / "subs.jsonl", http=http)


# ------------------------------------------------------------------ search
@pytest.mark.parametrize("mode", ["visual", "speech", "fused"])
def test_text_modes(client, mode):
    r = client.post("/search/text", json={"q": "people talking on a stage", "mode": mode, "k": 50})
    assert r.status_code == 200, r.text
    res = r.json()["results"]
    assert res and len(res) <= 50
    assert {"shot_id", "v3c_id", "start_ms", "end_ms", "score", "title", "snippet"} <= res[0].keys()
    assert all(a["score"] >= b["score"] for a, b in zip(res, res[1:]))
    assert "X-Search-Ms" in r.headers


def test_group_by_video(client):
    res = client.post("/search/text", json={"q": "mountains", "mode": "visual", "k": 10,
                                            "group_by_video": True}).json()["results"]
    vids = [x["v3c_id"] for x in res]
    assert len(vids) == len(set(vids)) == min(10, len(appmod.S["engine"].video_rows))


def test_image_query_finds_itself(client, some_shot):
    png = (config.THUMBS / some_shot.thumb_path).read_bytes()
    r = client.post("/search/image", files={"file": ("x.png", png, "image/png")}, data={"k": "5"})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["shot_id"] == some_shot.shot_id


def test_image_rejects_garbage(client):
    r = client.post("/search/image", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 400


def test_similar(client, some_shot):
    res = client.get(f"/search/similar/{some_shot.shot_id}?k=5").json()["results"]
    assert res[0]["shot_id"] == some_shot.shot_id
    assert client.get("/search/similar/shot99999_1").status_code == 404


def test_temporal(client):
    r = client.post("/search/temporal", json={"qa": "a person speaking", "qb": "a crowd", "max_shots": 3, "k": 20})
    assert r.status_code == 200, r.text
    for x in r.json()["results"]:
        nb = x["next_shot"]
        assert nb["v3c_id"] == x["v3c_id"] and 1 <= nb["n"] - x["n"] <= 3
    r = client.post("/search/temporal", json={"qa": "a person speaking", "qb": "a crowd", "max_shots": 3,
                                              "max_seconds": 2, "k": 20})
    for x in r.json()["results"]:
        assert x["next_shot"]["start_ms"] - x["end_ms"] <= 2000


def test_feedback(client, some_shot):
    r = client.post("/search/feedback", json={"positives": [some_shot.shot_id], "k": 5})
    assert r.status_code == 200 and r.json()["results"][0]["shot_id"] == some_shot.shot_id
    assert client.post("/search/feedback", json={"positives": []}).status_code == 400


def test_latency_logged(client):
    lines = (config.LOGS / "latency.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["ms"] > 0


# ------------------------------------------------------------------ media
def test_video_shots(client, some_shot):
    r = client.get(f"/video/{some_shot.v3c_id}/shots").json()
    assert r["v3c_id"] == some_shot.v3c_id and r["shots"][0]["n"] == 1
    assert [s["n"] for s in r["shots"]] == list(range(1, len(r["shots"]) + 1))


def test_thumb(client, some_shot):
    r = client.get(f"/thumb/{some_shot.shot_id}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    Image.open(io.BytesIO(r.content)).verify()


def test_video_range(client, some_shot):
    path = config.VIDEOS / f"{some_shot.v3c_id}.mp4"
    data, size = path.read_bytes(), path.stat().st_size
    url = f"/video/{some_shot.v3c_id}.mp4"

    r = client.get(url, headers={"Range": "bytes=1000-2000"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 1000-2000/{size}"
    assert r.headers["accept-ranges"] == "bytes" and r.content == data[1000:2001]

    r = client.get(url, headers={"Range": "bytes=-500"})
    assert r.status_code == 206 and r.content == data[-500:]

    r = client.get(url, headers={"Range": f"bytes={size - 10}-"})
    assert r.status_code == 206 and r.content == data[-10:]

    assert client.get(url, headers={"Range": f"bytes={size}-"}).status_code == 416

    r = client.get(url)
    assert r.status_code == 200 and int(r.headers["content-length"]) == size
    assert client.get("/video/99999.mp4").status_code == 404


# ------------------------------------------------------------------ DRES
def test_dres_client_v2(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TARGET", "00031:3586-8008")
    d = fake_dres_client(tmp_path)
    d.login()
    ev = d.active_evaluation()
    assert ev["id"] == "eval-1"
    assert d.submit(ev["id"], "00031", 3586, 8008)["verdict"] == "CORRECT"
    assert d.submit(ev["id"], "00032", 0, 1000)["verdict"] == "WRONG"
    bad = d.submit("nope", "00031", 0, 10)
    assert bad["verdict"] == "ERROR" and bad["http_status"] == 404
    log = [json.loads(x) for x in (tmp_path / "subs.jsonl").read_text().splitlines()]
    assert [x["verdict"] for x in log] == ["CORRECT", "WRONG", "ERROR"]
    assert log[0]["request"] == {"answerSets": [{"answers": [{"mediaItemName": "00031", "start": 3586, "end": 8008}]}]}


def test_dres_relogin_on_401(tmp_path):
    d = fake_dres_client(tmp_path)
    d.login()
    fake_dres.SESSIONS.clear()          # server forgets the session
    assert d.evaluations()[0]["id"] == "eval-1"


def test_dres_bad_login(tmp_path):
    d = fake_dres_client(tmp_path)
    d.password = "wrong"
    with pytest.raises(DresError):
        d.login()


def test_dres_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TARGET", "00031:3586-8008")
    d = fake_dres_client(tmp_path, api="legacy")
    r = d.submit("", "00031", 3586, 8008, mid_frame=137)
    assert r["verdict"] == "CORRECT" and r["request"] == {"item": "00031", "frame": 137}


def test_dres_submit_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TARGET", "00031:3586-8008")
    monkeypatch.setitem(appmod.S, "dres", fake_dres_client(tmp_path))
    r = client.post("/dres/submit", json={"answers": [{"shot_id": "shot00031_2"},
                                                      {"v3c_id": "00031", "start_ms": 100000, "end_ms": 101000}]})
    assert r.status_code == 200, r.text
    v = [x["verdict"] for x in r.json()["results"]]
    assert v == ["CORRECT", "WRONG"]
    st = client.get("/dres/status").json()
    assert st["logged_in"] and st["active"][0]["id"] == "eval-1"
    assert client.post("/dres/submit", json={"answers": [{"shot_id": "shotXX_1"}]}).status_code == 400
