"""Mock KIS run: pick random target shots, query for them, report the rank of the target.

Query types:
  thumb      the shot's own thumbnail (sanity check: should be rank 1)
  frame      a frame grabbed from the 480p video at the shot's midpoint, degraded like a screenshot
             of a projected clip (5% crop, 640 px, JPEG q=60): the realistic KIS-V case
  speech     8 consecutive words of the shot's own transcript, speech (BM25) mode   (KIS-T proxy)
  fused      the same words, fused mode

A hit for a KIS answer means the submitted range covers the target. We report rank of the exact
shot (R@1/10/100, MRR), rank within +-1 shot (adjacent shots often look and sound the same), and
rank of the first result from the right video. Writes logs/selftest.json.

Usage: .venv/bin/python scripts/selftest.py [--n 200] [--seed 42]
"""
import argparse
import io
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from backend.engine import Engine  # noqa: E402

DEPTH = 1000


def grab_frame(v3c, t_ms):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t_ms / 1000:.3f}", "-i", str(config.VIDEOS / f"{v3c}.mp4"),
                          "-frames:v", "1", "-f", "image2", "-c:v", "png", "-"], capture_output=True)
    if out.returncode or not out.stdout:
        return None
    img = Image.open(io.BytesIO(out.stdout)).convert("RGB")
    w, h = img.size
    img = img.crop((int(w * .05), int(h * .05), int(w * .95), int(h * .95))).resize((640, int(640 * h / w)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return Image.open(io.BytesIO(buf.getvalue()))


def ranks(engine, rows, target):
    """(exact rank, rank within +-1 shot of the same video, first rank of the right video); None = not in top DEPTH."""
    vid, n = engine.vid[target], engine.shots.n.iat[target]
    exact = near = video = None
    for i, r in enumerate(rows, 1):
        if engine.vid[r] == vid:
            video = video or i
            if abs(engine.shots.n.iat[r] - n) <= 1:
                near = near or i
            if r == target:
                exact = i
                break
    return exact, near, video


def summarize(rs):
    def stats(xs):
        return {"R@1": np.mean([x is not None and x <= 1 for x in xs]).round(3),
                "R@10": np.mean([x is not None and x <= 10 for x in xs]).round(3),
                "R@100": np.mean([x is not None and x <= 100 for x in xs]).round(3),
                "MRR": np.mean([1 / x if x else 0 for x in xs]).round(3)}
    return {"n": len(rs), "exact": stats([r[0] for r in rs]), "within_1_shot": stats([r[1] for r in rs]),
            "video": stats([r[2] for r in rs])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    e = Engine()
    have_video = {p.stem for p in config.VIDEOS.glob("*.mp4")}
    targets = rnd.sample(range(len(e.shots)), min(args.n, len(e.shots)))
    res = {"thumb": [], "frame": [], "speech": [], "fused": []}
    for i, t in enumerate(targets):
        row = e.shots.iloc[t]
        thumb = Image.open(config.THUMBS / row.thumb_path)
        res["thumb"].append(ranks(e, e.image(thumb, DEPTH)[0], t))
        if row.v3c_id in have_video:
            frame = grab_frame(row.v3c_id, (row.start_ms + row.end_ms) // 2)
            if frame is not None:
                res["frame"].append(ranks(e, e.image(frame, DEPTH)[0], t))
        words = re.findall(r"\w+", e.text[t])
        if len(words) >= 8:
            j = rnd.randrange(len(words) - 7)
            q = " ".join(words[j:j + 8])
            res["speech"].append(ranks(e, e.speech(q, DEPTH)[0], t))
            res["fused"].append(ranks(e, e.fused(q, DEPTH)[0], t))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(targets)}", flush=True)

    out = {"shots": len(e.shots), "videos": len(e.video_rows), "model": e.model_info["model"],
           "seed": args.seed, "depth": DEPTH, "results": {k: summarize(v) for k, v in res.items() if v}}
    print(f"\n{out['shots']} shots / {out['videos']} videos, {len(targets)} targets (seed {args.seed})")
    print(f"{'query':<8} {'n':>4} | {'exact R@1':>9} {'R@10':>6} {'R@100':>6} {'MRR':>6} | "
          f"{'±1 R@10':>7} | {'video R@1':>9} {'R@10':>6}")
    for k, s in out["results"].items():
        ex, nb, vd = s["exact"], s["within_1_shot"], s["video"]
        print(f"{k:<8} {s['n']:>4} | {ex['R@1']:>9} {ex['R@10']:>6} {ex['R@100']:>6} {ex['MRR']:>6} | "
              f"{nb['R@10']:>7} | {vd['R@1']:>9} {vd['R@10']:>6}")
    config.LOGS.mkdir(exist_ok=True)
    (config.LOGS / "selftest.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
