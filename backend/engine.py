"""In-memory search engine: loads all index artifacts once and answers every query type.

Shared by the FastAPI app and the offline scripts (sample queries, benchmark, selftest).
All scores are "higher is better". Every search returns a list of result dicts.
"""
import json
import sys
from pathlib import Path

import bm25s
import numpy as np
import pandas as pd
import Stemmer
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def _device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


class Engine:
    def __init__(self, load_model: bool = True):
        self.shots = pd.read_parquet(config.SHOTS_PARQUET)
        self.videos = pd.read_parquet(config.VIDEOS_PARQUET).set_index("v3c_id")
        self.text = pd.read_parquet(config.SHOT_TEXT).text.to_numpy()
        self.emb = np.load(config.IMG_EMB).astype(np.float32)
        assert len(self.shots) == len(self.emb) == len(self.text)

        self.shot_ids = self.shots.shot_id.to_numpy()
        self.vid = self.shots.v3c_id.to_numpy()
        self.start_ms = self.shots.start_ms.to_numpy()
        self.end_ms = self.shots.end_ms.to_numpy()
        self.row_of = {s: i for i, s in enumerate(self.shot_ids)}
        # contiguous row range of every video (shots.parquet is ordered by video, then n)
        first = self.shots.groupby("v3c_id", sort=False).row.agg(["min", "max"])
        self.video_rows = {v: (int(a), int(b) + 1) for v, (a, b) in first.iterrows()}

        self.stemmer = Stemmer.Stemmer("english")
        self.bm_shots = bm25s.BM25.load(config.BM25_SHOTS)
        self.bm_meta = bm25s.BM25.load(config.BM25_META)
        meta_videos = (config.BM25_META / "videos.txt").read_text().split("\n")
        vpos = {v: i for i, v in enumerate(meta_videos)}
        self.shot_meta_idx = np.array([vpos[v] for v in self.vid])

        self.model_info = json.loads(config.EMB_META.read_text())
        self.model = None
        if load_model:
            self._load_model()

    # ---------------------------------------------------------------- model
    def _load_model(self):
        import open_clip
        name, pre = self.model_info["model"], self.model_info["pretrained"]
        model, _, self.preprocess = open_clip.create_model_and_transforms(name, pretrained=pre)
        self.dev = _device()
        self.model = model.eval().to(self.dev)
        if self.dev == "mps":
            self.model = self.model.half()
        self.tokenizer = open_clip.get_tokenizer(name)

    @torch.no_grad()
    def embed_text(self, q: str) -> np.ndarray:
        e = self.model.encode_text(self.tokenizer([q]).to(self.dev)).float()
        return torch.nn.functional.normalize(e, dim=-1)[0].cpu().numpy()

    @torch.no_grad()
    def embed_image(self, img) -> np.ndarray:
        x = self.preprocess(img.convert("RGB")).unsqueeze(0).to(self.dev, dtype=next(self.model.parameters()).dtype)
        e = self.model.encode_image(x).float()
        return torch.nn.functional.normalize(e, dim=-1)[0].cpu().numpy()

    # ---------------------------------------------------------------- scoring primitives
    def _knn(self, qvec: np.ndarray, k: int):
        # Exact inner-product search (same result as faiss IndexFlatIP). faiss is not used in
        # this process: its bundled libomp conflicts with torch's and segfaults on macOS.
        return self._top(self.emb @ qvec.astype(np.float32), k)

    def speech_scores(self, q: str) -> np.ndarray:
        """BM25 over shot transcripts + META_WEIGHT * BM25 over the shot's video metadata."""
        toks = bm25s.tokenize(q, stopwords="en", stemmer=self.stemmer, return_ids=False, show_progress=False)[0]
        s = np.zeros(len(self.shots), dtype=np.float32)
        t_shot = [t for t in toks if t in self.bm_shots.vocab_dict]
        t_meta = [t for t in toks if t in self.bm_meta.vocab_dict]
        if t_shot:
            s += self.bm_shots.get_scores(t_shot)
        if t_meta:
            s += config.META_WEIGHT * self.bm_meta.get_scores(t_meta)[self.shot_meta_idx]
        return s

    @staticmethod
    def _top(scores: np.ndarray, k: int, positive_only=False):
        k = min(k, len(scores))
        rows = np.argpartition(-scores, k - 1)[:k]
        rows = rows[np.argsort(-scores[rows])]
        if positive_only:
            rows = rows[scores[rows] > 0]
        return rows, scores[rows]

    # ---------------------------------------------------------------- searches
    def visual(self, q: str, k=200):
        return self._knn(self.embed_text(q), k)

    def speech(self, q: str, k=200):
        return self._top(self.speech_scores(q), k, positive_only=True)

    @staticmethod
    def speech_weight(speech_scores: np.ndarray) -> float:
        """RRF weight of the speech ranking, from how much the best BM25 match stands out.

        Spoken-word queries tend to have one standout match (top-50 score far below top-1); visual
        descriptions match many shots weakly. Confidence 1 - s50/s1 is mapped linearly from
        SPEECH_CONF_LO..LO+SPAN to weight 1..SPEECH_WEIGHT_MAX.
        """
        top = np.partition(speech_scores, len(speech_scores) - 50)[-50:]
        s1, s50 = top.max(), top.min()
        conf = 0.0 if s1 <= 0 else 1 - s50 / s1
        t = np.clip((conf - config.SPEECH_CONF_LO) / config.SPEECH_CONF_SPAN, 0, 1)
        return float(1 + (config.SPEECH_WEIGHT_MAX - 1) * t)

    def fused(self, q: str, k=200):
        """Weighted reciprocal rank fusion of the visual and speech rankings (speech weight adapts to the query)."""
        s = self.speech_scores(q)
        rrf = np.zeros(len(self.shots), dtype=np.float32)
        vis, _ = self.visual(q, config.FUSION_DEPTH)
        sp, _ = self._top(s, config.FUSION_DEPTH, positive_only=True)
        for rows, w in ((vis, 1.0), (sp, self.speech_weight(s))):
            rrf[rows] += w / (config.RRF_K + np.arange(1, len(rows) + 1))
        return self._top(rrf, k, positive_only=True)

    def image(self, img, k=200):
        return self._knn(self.embed_image(img), k)

    def similar(self, shot_id: str, k=200):
        return self._knn(self.emb[self.row_of[shot_id]], k)

    def feedback(self, positives, negatives=(), q: str | None = None, k=200,
                 alpha=1.0, beta=0.75, gamma=0.25):
        """Rocchio on the image-embedding space; q (optional) is the original text query."""
        vec = np.zeros(self.emb.shape[1], dtype=np.float32)
        if q:
            vec += alpha * self.embed_text(q)
        if positives:
            vec += beta * self.emb[[self.row_of[s] for s in positives]].mean(0)
        if negatives:
            vec -= gamma * self.emb[[self.row_of[s] for s in negatives]].mean(0)
        return self._knn(vec / (np.linalg.norm(vec) + 1e-9), k)

    def temporal(self, qa: str, qb: str, k=200, max_shots=5, max_seconds=None, mode="visual"):
        """Shots matching A followed (same video, within max_shots shots and/or max_seconds) by B.

        Returns (rows_a, scores, rows_b): rows_b[i] is the best-matching B shot after rows_a[i].
        """
        def sims(q):
            if mode == "speech":
                s = self.speech_scores(q)
                return s / (s.max() + 1e-9)
            return self.emb @ self.embed_text(q)
        sa, sb = sims(qa), sims(qb)
        n = len(sa)
        best_b = np.full(n, -np.inf, dtype=np.float32)
        best_j = np.full(n, -1)
        for d in range(1, max_shots + 1):
            i = np.arange(n - d)
            ok = self.vid[i] == self.vid[i + d]
            if max_seconds is not None:
                ok &= (self.start_ms[i + d] - self.end_ms[i]) <= max_seconds * 1000
            cand = np.where(ok, sb[i + d], -np.inf)
            better = cand > best_b[i]
            best_b[i] = np.where(better, cand, best_b[i])
            best_j[i] = np.where(better, i + d, best_j[i])
        total = np.where(best_j >= 0, sa + best_b, -np.inf)
        rows, scores = self._top(total, k)
        keep = np.isfinite(scores)
        return rows[keep], scores[keep], best_j[rows[keep]]

    # ---------------------------------------------------------------- results
    def result(self, row: int, score: float, **extra) -> dict:
        v = self.vid[row]
        return {"row": int(row), "shot_id": self.shot_ids[row], "v3c_id": v,
                "n": int(self.shots.n.iat[row]), "start_ms": int(self.start_ms[row]),
                "end_ms": int(self.end_ms[row]), "score": float(score),
                "title": self.videos.at[v, "title"], "snippet": self.text[row][:300], **extra}

    def results(self, rows, scores, group_by_video=False, k=None):
        out, seen = [], set()
        for r, s in zip(rows, scores):
            if group_by_video:
                if self.vid[r] in seen:
                    continue
                seen.add(self.vid[r])
            out.append(self.result(r, s))
            if k and len(out) >= k:
                break
        return out
