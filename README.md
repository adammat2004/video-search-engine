# VBS-style interactive video retrieval (V3C1, 1k sample)

Search Technologies, Assignment 2.

- `indexer/`: offline pipeline (see `indexer/FORMATS.md` for verified data formats)
- `backend/`: FastAPI search + media + DRES proxy
- `frontend/`: React + Vite UI
- `scripts/`: benchmarks and evaluation helpers
- `docs/report_material.md`: pipeline, external resources, numbers and limitations for the report

## Setup

Keep this repository **private**. The handout forbids sharing the collection or the system outside the group.

Prerequisites: an Apple-silicon Mac (SigLIP runs on the MPS GPU; CPU works but embedding is far slower),
[uv](https://docs.astral.sh/uv/), Node 20+, Google Chrome, ffmpeg. You also need about 45 GB of free disk.

    brew install ffmpeg
    uv python install 3.11
    uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
    (cd frontend && npm ci)

Data goes in `data/`, which is gitignored and never committed.

    # student_download.py ships with the assignment handout (it is not in this repo)
    python3 /path/to/student_download.py --packages metadata,msb,thumbnails,videos_480p --dest data/assignment2_data
    # Whisper transcripts (CC-BY-4.0): https://zenodo.org/records/7383303 -> V3C1.zip
    mkdir -p data/whisper && unzip -q V3C1.zip -d data/whisper      # gives data/whisper/V3C1/<v3cId>.srt

DRES credentials are per person. Put your own login in `.env`, which is gitignored and never committed:

    cp .env.example .env    # DRES_URL=https://csc1103.interactivevideoretrieval.com, DRES_USER=<your DCU email>, DRES_PASS=...

`MEDIA_NAME_FMT={v3c_id}` (e.g. `00031`) is confirmed correct against the course server.

## Build the index

    indexer/run_all.sh            # idempotent; re-run after downloading more videos

This takes about 2 h for the full corpus, almost all of it SigLIP embedding (20–25 img/s on an M-series GPU).
Keep the Mac plugged in with the lid open: sleep pauses it. It resumes where it stopped.

**Shortcut:** copy a teammate's `index/` folder (about 7 GB; `index/thumbs` is most of it) into the repo
instead. The backend then starts immediately. You still need `data/` for video playback.

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
