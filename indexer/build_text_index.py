"""Assign Whisper segments to shots and build the BM25 indexes.

- index/shot_text.parquet: per shot (aligned to shots.parquet rows) its own transcript text.
- index/bm25_shots/: BM25 over shot documents = own transcript (x2) + transcript of the
  +-NEIGHBOUR_WINDOW neighbouring shots (x1), because speech often runs across shot cuts.
- index/bm25_meta/: BM25 over one document per video = title (x2) + tags + description.
  At query time the shot score is bm25_shot + META_WEIGHT * bm25_meta(video of shot).

SRT format and noise handling per indexer/FORMATS.md.
"""
import re

import bm25s
import numpy as np
import pandas as pd
import Stemmer

from common import build_step, config, is_fresh

TS = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")
FILLER = re.compile(r"[\W_]*|\[?music\]?|♪+|you\.?|thank you\.?|thanks for watching!?", re.I)


def parse_srt(v: str, duration_ms: int):
    path = config.WHISPER / f"{v}.srt"
    if not path.exists():
        return []
    segs = []
    for block in path.read_text(encoding="utf-8", errors="replace").strip().split("\n\n"):
        m = TS.search(block)
        if not m:
            continue
        g = list(map(int, m.groups()))
        s = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
        e = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
        text = " ".join(block.splitlines()[2:]).strip()
        if not text or FILLER.fullmatch(text) or s >= duration_ms:
            continue
        segs.append((s, min(e, duration_ms), text))
    return segs


def tokenizer():
    return Stemmer.Stemmer("english")


def tokenize(texts):
    return bm25s.tokenize(texts, stopwords="en", stemmer=tokenizer(), show_progress=False)


def main():
    outs = [config.SHOT_TEXT, config.BM25_SHOTS / "params.index.json", config.BM25_META / "params.index.json"]
    if is_fresh(outs, [config.SHOTS_PARQUET, config.VIDEOS_PARQUET]):
        print("[build_text_index] up to date"); return

    with build_step("build_text_index", outputs=[config.SHOT_TEXT, config.BM25_SHOTS, config.BM25_META]) as info:
        shots = pd.read_parquet(config.SHOTS_PARQUET)
        videos = pd.read_parquet(config.VIDEOS_PARQUET).set_index("v3c_id")
        own = [""] * len(shots)
        n_segs = 0
        for v, g in shots.groupby("v3c_id", sort=False):
            segs = parse_srt(v, int(videos.at[v, "duration_s"] * 1000) + 1000)
            n_segs += len(segs)
            starts, ends, rows = g.start_ms.to_numpy(), g.end_ms.to_numpy(), g.row.to_numpy()
            parts = {r: [] for r in rows}
            for s, e, text in segs:
                # every shot the segment overlaps; segments that fall in a gap go to the nearest shot
                hit = np.nonzero((starts < e) & (ends > s))[0]
                if len(hit) == 0:
                    hit = [int(np.argmin(np.abs(starts - s)))]
                for i in hit:
                    parts[rows[i]].append(text)
            for r, texts in parts.items():
                own[r] = " ".join(dict.fromkeys(texts))  # dedupe, keep order

        w = config.NEIGHBOUR_WINDOW
        vid = shots.v3c_id.to_numpy()
        docs = []
        for r in range(len(shots)):
            nb = [own[j] for j in range(max(0, r - w), min(len(shots), r + w + 1))
                  if j != r and vid[j] == vid[r] and own[j] != own[r]]
            docs.append(" ".join([own[r], own[r], *nb]))

        pd.DataFrame({"row": shots.row, "text": own}).to_parquet(config.SHOT_TEXT, index=False)

        bm_shots = bm25s.BM25()
        bm_shots.index(tokenize(docs), show_progress=False)
        bm_shots.save(config.BM25_SHOTS, show_progress=False)

        vdocs = [" ".join([t, t, tags.replace(";", " "), cats.replace("/categories/", " ").replace("/", " "), d])
                 for t, tags, cats, d in zip(videos.title, videos.tags, videos.categories, videos.description)]
        bm_meta = bm25s.BM25()
        bm_meta.index(tokenize(vdocs), show_progress=False)
        bm_meta.save(config.BM25_META, show_progress=False)
        (config.BM25_META / "videos.txt").write_text("\n".join(videos.index))

        info.update(segments=n_segs, shots_with_speech=int(sum(bool(t) for t in own)), shots=len(shots),
                    vocab_shots=len(bm_shots.vocab_dict), vocab_meta=len(bm_meta.vocab_dict))


if __name__ == "__main__":
    main()
