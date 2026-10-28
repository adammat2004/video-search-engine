# VBS-style interactive video retrieval (V3C1, 1k sample)

Search Technologies, Assignment 2.

- `indexer/`: offline pipeline (see `indexer/FORMATS.md` for verified data formats)
- `backend/`: FastAPI search + media + DRES proxy
- `frontend/`: React + Vite UI
- `scripts/`: benchmarks and evaluation helpers

## Setup

    uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
    brew install ffmpeg
    python3 ../student_download.py --packages metadata,msb,thumbnails,videos_480p --dest data/assignment2_data
    # Whisper transcripts: https://zenodo.org/records/7383303 (V3C1.zip) -> data/whisper/
    cp .env.example .env   # fill in DRES credentials
