"""Run a few text queries in every mode and print the top results (Phase 1 checkpoint).

Also writes a contact sheet (index/samples/<mode>.png) with the top thumbnails per query.
Usage: python scripts/sample_queries.py ["query 1" "query 2" ...]
"""
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from backend.engine import Engine  # noqa: E402

QUERIES = [
    "a person balancing on a highline rope above a valley",
    "paraglider flying over snowy mountains",
    "a goose swimming in a pond",
    "growing vegetables in a hydroponic farm",
    "people talking about addiction and recovery",
]
TOP = 5


def sheet(engine, rows_per_query, path):
    w, h = 200, 113
    img = Image.new("RGB", (w * TOP, (h + 14) * len(rows_per_query)), "white")
    d = ImageDraw.Draw(img)
    for qi, (q, rows) in enumerate(rows_per_query):
        y = qi * (h + 14)
        d.text((2, y), q[:60], fill="black")
        for j, r in enumerate(rows[:TOP]):
            t = Image.open(config.THUMBS / engine.shots.thumb_path.iat[r]).convert("RGB")
            t.thumbnail((w, h))
            img.paste(t, (j * w, y + 14))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main():
    queries = sys.argv[1:] or QUERIES
    e = Engine()
    e.visual("warmup")
    sheets = {m: [] for m in ("visual", "speech", "fused")}
    for q in queries:
        print(f"\n=== {q}")
        for mode in sheets:
            t = time.perf_counter()
            rows, scores = getattr(e, mode)(q, 50)
            ms = (time.perf_counter() - t) * 1000
            sheets[mode].append((q, list(rows)))
            print(f"  [{mode}] {ms:.0f} ms")
            for r, s in list(zip(rows, scores))[:TOP]:
                res = e.result(r, s)
                print(f"    {res['shot_id']:<16} {res['start_ms']:>8}-{res['end_ms']:<8} {s:7.3f}  "
                      f"{res['title'][:34]:<34} | {res['snippet'][:50]}")
    for mode, rows in sheets.items():
        sheet(e, rows, config.INDEX / "samples" / f"{mode}.png")
    print(f"\ncontact sheets in {config.INDEX / 'samples'}")


if __name__ == "__main__":
    main()
