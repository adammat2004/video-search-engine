"""Query latency benchmark through the HTTP API, plus the backend's RAM footprint.

Needs the backend running (default http://127.0.0.1:8000). Reports client-side wall time and the
server-side time (X-Search-Ms header) as p50/p95 per search mode, and the backend process RSS.
Writes logs/benchmark.json.

Usage: .venv/bin/python scripts/benchmark.py [--n 200] [--url http://127.0.0.1:8000]
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

QUERIES = [
    "a man playing guitar on stage", "aerial view of a city at night", "a dog running on the beach",
    "people dancing at a wedding", "snow covered mountains", "a car driving on a highway",
    "close-up of a woman's face", "children playing football", "a sunset over the ocean",
    "cooking food in a kitchen", "a crowd at a concert", "skateboarder doing a trick",
    "a red flower in a garden", "underwater shot of fish", "text on a black screen",
    "people talking about climate change", "interview in an office", "a train passing by",
    "fireworks in the sky", "a cat sitting on a sofa", "hands typing on a keyboard",
    "a river in a forest", "a bride and groom", "drone footage of a coastline",
    "a man speaking into a microphone", "time-lapse of clouds", "a boat on a lake",
    "a bicycle race", "a church interior", "graffiti on a wall",
]
PAIRS = [("a person walking", "a close-up of a face"), ("a city street", "a building at night"),
         ("mountains", "a person on a summit"), ("a stage with lights", "an audience clapping")]


def pct(xs, p):
    return round(float(np.percentile(xs, p)), 1) if xs else None


def backend_rss_mb():
    for proc in psutil.process_iter(["cmdline"]):
        cmd = " ".join(proc.info["cmdline"] or [])
        if "uvicorn" in cmd and "backend.app" in cmd:
            return round(proc.memory_info().rss / 2**20)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    rnd = random.Random(0)
    shots = pd.read_parquet(config.SHOTS_PARQUET)
    sample = shots.sample(n=min(args.n, len(shots)), random_state=0)
    c = httpx.Client(base_url=args.url, timeout=60)

    def q_text(mode):
        return lambda i: c.post("/search/text", json={"q": QUERIES[i % len(QUERIES)], "mode": mode, "k": 200})

    def q_image(i):
        row = sample.iloc[i % len(sample)]
        png = (config.THUMBS / row.thumb_path).read_bytes()
        return c.post("/search/image", files={"file": ("q.png", png, "image/png")}, data={"k": "200"})

    def q_similar(i):
        return c.get(f"/search/similar/{sample.iloc[i % len(sample)].shot_id}?k=200")

    def q_temporal(i):
        a, b = PAIRS[i % len(PAIRS)]
        return c.post("/search/temporal", json={"qa": a, "qb": b, "max_shots": 5, "k": 200})

    def q_feedback(i):
        pos = [sample.iloc[(i + j) % len(sample)].shot_id for j in range(3)]
        return c.post("/search/feedback", json={"positives": pos, "negatives": [], "k": 200})

    def q_grouped(i):
        return c.post("/search/text", json={"q": QUERIES[i % len(QUERIES)], "mode": "fused", "k": 200,
                                            "group_by_video": True})

    modes = {"visual": q_text("visual"), "speech": q_text("speech"), "fused": q_text("fused"),
             "fused+group": q_grouped, "image": q_image, "similar": q_similar, "temporal": q_temporal,
             "feedback": q_feedback}
    out = {"shots": len(shots), "videos": int(shots.v3c_id.nunique()), "n_per_mode": args.n, "modes": {}}
    print(f"{len(shots)} shots / {out['videos']} videos, {args.n} queries per mode")
    print(f"{'mode':<12} {'client p50':>10} {'p95':>7} {'server p50':>11} {'p95':>7}  (ms)")
    for name, fn in modes.items():
        for i in range(3):
            fn(i)  # warm-up
        wall, server = [], []
        for i in range(args.n):
            t = time.perf_counter()
            r = fn(rnd.randrange(10_000))
            wall.append((time.perf_counter() - t) * 1000)
            r.raise_for_status()
            server.append(float(r.headers["x-search-ms"]))
        out["modes"][name] = {"client_p50": pct(wall, 50), "client_p95": pct(wall, 95),
                              "server_p50": pct(server, 50), "server_p95": pct(server, 95)}
        m = out["modes"][name]
        print(f"{name:<12} {m['client_p50']:>10} {m['client_p95']:>7} {m['server_p50']:>11} {m['server_p95']:>7}")
    out["backend_rss_mb"] = backend_rss_mb()
    print(f"backend RSS: {out['backend_rss_mb']} MB")
    config.LOGS.mkdir(exist_ok=True)
    (config.LOGS / "benchmark.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
