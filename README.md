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

## Build the index

    indexer/run_all.sh            # idempotent; re-run after downloading more videos

## Run

    .venv/bin/uvicorn backend.app:app --port 8000          # backend (loads index + SigLIP, ~10 s)
    cd frontend && npm install && npx vite --port 5173      # UI at http://localhost:5173

Practice without the course server: `.venv/bin/uvicorn scripts.fake_dres:app --port 8081` and set
`DRES_URL=http://127.0.0.1:8081`, `DRES_USER=team`, `DRES_PASS=secret` in `.env`
(target segment: `FAKE_TARGET=00031:3586-8008`).

## Keyboard

| Key | Action |
|---|---|
| `/` | focus query (Enter searches, Esc leaves the box) |
| `00031` / `00031 1` | jump to a video by id (all its shots) / straight to shot 1 in the player |
| `1`–`4` | Visual / Speech / Fused / Temporal A→B |
| ⌘V | search by pasted screenshot (⌘⌃⇧4 copies a screen region) |
| arrows | move selection · `Space` play selected · `M` more like this |
| `[` / `]` / `R` | set range start / end to playback time · reset to shot |
| `L` / `K` | toggle loop / play-pause |
| `S` then `Y` | submit (KIS: player range; AVS: queue) · `Esc` cancels |
| `A` | add/remove selected shot to AVS queue |
| `P` / `X` / `F` | mark positive / negative, run relevance-feedback search |
| `G` | best shot per video · `T` toggle KIS/AVS · `⇧N` new task |

## Tests

    .venv/bin/pytest -q                       # backend + DRES client (needs the index)
    # UI end-to-end in Chrome. It submits WRONG answers on purpose, so it only runs against the fake DRES;
    # use a separate test stack so the real backend can stay on the course server:
    .venv/bin/uvicorn scripts.fake_dres:app --port 8081 &
    DRES_URL=http://127.0.0.1:8081 DRES_USER=team DRES_PASS=secret VBS_SUBMIT_LOG=logs/submissions_test.jsonl \
        .venv/bin/uvicorn backend.app:app --port 8001 &
    (cd frontend && VBS_BACKEND=http://127.0.0.1:8001 npx vite --port 5174 &)
    VBS_UI_URL=http://localhost:5174 .venv/bin/python scripts/ui_e2e.py

## During an evaluation

The UI follows the DRES task by itself: when a new task starts it clears the results and queue and
selects KIS or AVS from the task's group. The countdown next to the DRES status shows the time left
(red in the last minute). `⇧N` still resets by hand if needed.
