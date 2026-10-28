"""Central configuration shared by the indexer, backend and scripts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "assignment2_data"
WHISPER = ROOT / "data" / "whisper" / "V3C1"
INDEX = ROOT / "index"
LOGS = ROOT / "logs"

MSB_ZIP = DATA / "msb.zip"
METADATA_JSON = DATA / "videos_metadata.json"
THUMB_ZIPS = DATA / "thumbnails"
VIDEOS = DATA / "videos_480p"

SHOTS_PARQUET = INDEX / "shots.parquet"
VIDEOS_PARQUET = INDEX / "videos.parquet"
THUMBS = INDEX / "thumbs"
EMB_DIR = INDEX / "emb"
IMG_EMB = INDEX / "img_emb.f16.npy"
EMB_META = INDEX / "img_emb.json"
FAISS_INDEX = INDEX / "img.faiss"
BM25_SHOTS = INDEX / "bm25_shots"
BM25_META = INDEX / "bm25_meta"
SHOT_TEXT = INDEX / "shot_text.parquet"
BUILD_LOG = INDEX / "build_log.jsonl"

# Visual model (OpenCLIP name, pretrained tag). Fallback is used if the main one is too slow.
CLIP_MODEL = ("ViT-SO400M-14-SigLIP-384", "webli")
CLIP_FALLBACK = ("ViT-B-16-SigLIP-384", "webli")
EMBED_BATCH = 64

# Text ranking
META_WEIGHT = 0.3      # weight of per-video metadata BM25 relative to shot transcript BM25
NEIGHBOUR_WINDOW = 1   # transcript of +-N neighbouring shots is added to each shot's text
RRF_K = 60
FUSION_DEPTH = 1000

MIN_SHOT_MS = 40       # pad degenerate (zero-length) shots on submit
