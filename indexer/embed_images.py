"""Embed every shot thumbnail with an OpenCLIP model on MPS.

Embeddings are cached per video in index/emb/<model>/<v3cId>.npy, so the job resumes after an
interruption and only new videos are embedded when the corpus grows. The cache is then merged
into index/img_emb.f16.npy (L2-normalised float16, row i == shots.parquet row i).

Usage: python embed_images.py [--fallback]
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from common import build_step, config


class Thumbs(Dataset):
    def __init__(self, paths, preprocess):
        self.paths, self.preprocess = paths, preprocess

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        return self.preprocess(Image.open(config.THUMBS / self.paths[i]).convert("RGB"))


def device() -> str:
    return "mps" if torch.backends.mps.is_available() else "cpu"


def load_model(name, pretrained):
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(name, pretrained=pretrained)
    dev = device()
    model = model.eval().to(dev)
    if dev == "mps":
        model = model.half()  # 3x faster than fp32 on MPS; min cosine to fp32 >= 0.9998
    return model, preprocess, dev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fallback", action="store_true", help=f"use {config.CLIP_FALLBACK[0]}")
    args = ap.parse_args()
    name, pretrained = config.CLIP_FALLBACK if args.fallback else config.CLIP_MODEL

    shots = pd.read_parquet(config.SHOTS_PARQUET)
    cache = config.EMB_DIR / name
    cache.mkdir(parents=True, exist_ok=True)
    groups = {v: g.thumb_path.tolist() for v, g in shots.groupby("v3c_id", sort=False)}
    todo = [v for v, paths in groups.items()
            if not (cache / f"{v}.npy").exists() or len(np.load(cache / f"{v}.npy", mmap_mode="r")) != len(paths)]

    meta_ok = config.EMB_META.exists() and json.loads(config.EMB_META.read_text()) == \
        {"model": name, "pretrained": pretrained, "rows": len(shots)}
    if not todo and meta_ok and config.IMG_EMB.exists():
        print("[embed_images] up to date"); return

    with build_step("embed_images", outputs=[config.IMG_EMB]) as info:
        n_new = sum(len(groups[v]) for v in todo)
        if todo:
            model, preprocess, dev = load_model(name, pretrained)
            paths = [p for v in todo for p in groups[v]]
            loader = DataLoader(Thumbs(paths, preprocess), batch_size=config.EMBED_BATCH,
                                num_workers=6, persistent_workers=False)
            pending = iter(todo)
            cur, need, buf = next(pending), None, []
            need = len(groups[cur])
            done, t0 = 0, time.time()
            with torch.no_grad():
                for x in loader:
                    e = model.encode_image(x.to(dev, dtype=next(model.parameters()).dtype)).float()
                    e = torch.nn.functional.normalize(e, dim=-1).cpu().numpy().astype(np.float16)
                    buf.append(e)
                    done += len(e)
                    # flush every video whose rows are complete
                    while cur is not None and sum(len(b) for b in buf) >= need:
                        allv = np.concatenate(buf)
                        np.save(cache / f"{cur}.npy", allv[:need])
                        buf = [allv[need:]] if len(allv) > need else []
                        cur = next(pending, None)
                        need = len(groups[cur]) if cur else None
                    if done % (config.EMBED_BATCH * 20) < config.EMBED_BATCH:
                        rate = done / (time.time() - t0)
                        print(f"  {done}/{n_new}  {rate:.1f} img/s  eta {(n_new - done) / rate / 60:.1f} min",
                              flush=True)
            info["img_per_s"] = round(n_new / (time.time() - t0), 1)

        emb = np.concatenate([np.load(cache / f"{v}.npy") for v in groups])
        assert emb.shape[0] == len(shots), (emb.shape, len(shots))
        np.save(config.IMG_EMB, emb)
        config.EMB_META.write_text(json.dumps({"model": name, "pretrained": pretrained, "rows": len(shots)}))
        info.update(model=name, device=device(), embedded_now=n_new, rows=len(shots), dim=int(emb.shape[1]))


if __name__ == "__main__":
    main()
