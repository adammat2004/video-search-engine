"""Shared helpers for the indexer scripts: build logging and freshness checks."""
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def size_of(path: Path) -> int:
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def is_fresh(outputs, inputs) -> bool:
    """True if every output exists and is newer than every input."""
    outs = [Path(o) for o in outputs]
    ins = [Path(i) for i in inputs if Path(i).exists()]
    if not all(o.exists() for o in outs):
        return False
    oldest_out = min(o.stat().st_mtime for o in outs)
    newest_in = max((i.stat().st_mtime for i in ins), default=0)
    return oldest_out >= newest_in


@contextmanager
def build_step(step: str, outputs=()):
    """Time a build step and append wall time + output sizes to index/build_log.jsonl."""
    config.INDEX.mkdir(parents=True, exist_ok=True)
    extra = {}
    t0 = time.time()
    yield extra
    secs = time.time() - t0
    sizes = {str(Path(o).relative_to(config.ROOT)): size_of(o) for o in outputs}
    rec = {"step": step, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(secs, 2),
           "sizes": sizes, **extra}
    with open(config.BUILD_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[{step}] {secs:.1f}s  " + "  ".join(f"{k}={human(v)}" for k, v in sizes.items())
          + ("  " + json.dumps(extra) if extra else ""))


def available_videos() -> list[str]:
    """v3cIds whose thumbnail zip is present locally (the corpus is downloaded in batches)."""
    return sorted(p.stem for p in config.THUMB_ZIPS.glob("*.zip") if not p.name.endswith(".part"))


def ensure_cpu_threads():
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
