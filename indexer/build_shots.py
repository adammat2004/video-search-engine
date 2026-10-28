"""Build index/shots.parquet + index/videos.parquet and extract thumbnails to index/thumbs/.

Formats per indexer/FORMATS.md: msb times are SECONDS (converted to ms here), shot n is the
1-based data row, thumbnails are shot<v3cId>_<n>.png at the zip root.
Only videos whose thumbnail zip is present are included, so this can be re-run per batch.
"""
import html
import json
import re
import zipfile

import pandas as pd

from common import available_videos, build_step, config, is_fresh


def strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def extract_thumbs(v: str) -> int:
    out = config.THUMBS / v
    zpath = config.THUMB_ZIPS / f"{v}.zip"
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if n.endswith(".png")]
        if out.exists() and len(list(out.glob("*.png"))) == len(names):
            return 0
        out.mkdir(parents=True, exist_ok=True)
        for n in names:
            (out / n.rsplit("/", 1)[-1]).write_bytes(z.read(n))
    return len(names)


def main():
    vids = available_videos()
    zips = [config.THUMB_ZIPS / f"{v}.zip" for v in vids]
    outs = [config.SHOTS_PARQUET, config.VIDEOS_PARQUET]
    if is_fresh(outs, [config.MSB_ZIP, config.METADATA_JSON, *zips]) and \
            pd.read_parquet(config.VIDEOS_PARQUET).v3c_id.tolist() == vids:
        print("[build_shots] up to date"); return

    with build_step("build_shots", outputs=[*outs, config.THUMBS]) as info:
        meta = {m["v3cId"]: m for m in json.load(open(config.METADATA_JSON))}
        rows, extracted = [], 0
        with zipfile.ZipFile(config.MSB_ZIP) as msb:
            for v in vids:
                lines = msb.read(f"msb/{v}.tsv").decode().splitlines()
                assert lines[0].split("\t") == ["startframe", "starttime", "endframe", "endtime"], v
                for n, line in enumerate(lines[1:], start=1):
                    sf, st, ef, et = line.split("\t")
                    rows.append({
                        "shot_id": f"shot{v}_{n}", "v3c_id": v, "n": n,
                        "start_ms": round(float(st) * 1000), "end_ms": round(float(et) * 1000),
                        "start_frame": int(sf), "end_frame": int(ef),
                        "thumb_path": f"{v}/shot{v}_{n}.png",
                    })
                extracted += extract_thumbs(v)
        shots = pd.DataFrame(rows)
        shots.insert(0, "row", range(len(shots)))
        missing = [p for p in shots.thumb_path if not (config.THUMBS / p).exists()]
        assert not missing, f"{len(missing)} thumbnails missing, e.g. {missing[:3]}"

        videos = pd.DataFrame([{
            "v3c_id": v, "title": meta[v]["title"], "description": strip_html(meta[v]["description"]),
            "tags": meta[v]["tags"] or "", "categories": meta[v].get("categories") or "",
            "duration_s": float(meta[v]["duration"]), "shot_count": int(meta[v]["shot_count"]),
            "vimeo_url": meta[v]["vimeo_url"],
        } for v in vids])
        assert (videos.set_index("v3c_id").shot_count == shots.groupby("v3c_id").size()).all()

        config.INDEX.mkdir(exist_ok=True)
        shots.to_parquet(config.SHOTS_PARQUET, index=False)
        videos.to_parquet(config.VIDEOS_PARQUET, index=False)
        info.update(videos=len(videos), shots=len(shots), thumbs_extracted=extracted,
                    zero_length_shots=int((shots.end_ms <= shots.start_ms).sum()))


if __name__ == "__main__":
    main()
