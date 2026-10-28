#!/usr/bin/env bash
# Run the full (idempotent) indexing pipeline. Steps whose outputs are up to date are skipped.
set -euo pipefail
cd "$(dirname "$0")"
PY=../.venv/bin/python
$PY build_shots.py
$PY embed_images.py "$@"
$PY build_text_index.py
$PY build_faiss.py
