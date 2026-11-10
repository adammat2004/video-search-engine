# Report material

Raw material for the report (Methods / Results / Discussion / References). Numbers come from
`index/build_log.jsonl`, `logs/benchmark.json` and `logs/selftest.json`. Re-run the scripts to refresh them.

## 1. Pipeline

```
 OFFLINE (indexer/run_all.sh, idempotent)                     ONLINE (backend/app.py, all in RAM)
 ──────────────────────────────────────────                   ─────────────────────────────────────
 msb.zip ──► build_shots.py ──► shots.parquet ───────────────► shot table (id, video, n, start/end ms)
   (seconds → ms)     │                                         │
 thumbnails/*.zip ────┴──► index/thumbs/*.png ──┐               │   text query ──► SigLIP text tower ─┐
                                                ▼               │                                    ▼
                         embed_images.py (SigLIP SO400M/14-384, │   image paste ─► SigLIP image tower ► exact inner
                         MPS fp16, per-video cache) ──► img_emb.f16.npy ─────────────────────► product (numpy)
                                                ▼                                                     │
                         build_faiss.py ──► img.faiss (IndexFlatIP; reference artifact)               ├─► RRF fusion ──► results
 Whisper V3C1 SRT ──┐                                                                                  │   (k = 60)
 videos_metadata ───┴► build_text_index.py ──► bm25_shots (shot transcript ×2 + ±1 neighbours)        │
                       (segment→shot by time overlap,     bm25_meta (title ×2 + tags + categories     │
                        filler/hallucination filter)       + description), weight 0.3 ─────► BM25 ───┘
                                                                                                     
 Temporal A→B: per shot i, best B score among shots i+1…i+N of the same video (optionally within T s);
 score = s_A(i) + max s_B.   Relevance feedback: Rocchio q' = q + 0.75·mean(pos) − 0.25·mean(neg).
 UI (React) ─► FastAPI ─► DRES proxy (v2 OpenAPI: login → evaluation list → submit; legacy GET fallback)
```

Key points for the Methods section:

- **Shots.** We use the official master shot boundaries (msb) as the unit everywhere. TSV times are in **seconds** and are converted to ms (verified against ffprobe, see `indexer/FORMATS.md`). Submitted ranges are therefore exactly the official segments that AVS scoring maps onto. The user can still tighten a range in the player.
- **Visual embedding.** One embedding per shot, computed from its 200 px representative thumbnail with OpenCLIP `ViT-SO400M-14-SigLIP-384` (WebLI weights), 1152-d and L2-normalised.
  - It runs on Apple-silicon MPS in fp16, about 3× faster than fp32. The minimum cosine similarity to the fp32 embedding was 0.9998 on 256 thumbnails.
  - Embeddings are stored as float16 on disk and as float32 in RAM.
- **Search.** Exact maximum-inner-product search over all shots, using a numpy BLAS matrix–vector product plus `argpartition`.
  - A FAISS `IndexFlatIP` is built too. Loading faiss-cpu and PyTorch into one macOS process crashes, because each bundles its own OpenMP runtime (`libomp`). The exact numpy search returns the same ranking, and at this scale takes about 6 ms for 141k × 1152.
- **Text.** Whisper transcripts (Zenodo 7383303) are assigned to shots by time overlap.
  - Filler and hallucinated segments are dropped: "Music", "...", "You", "Thank you".
  - BM25 (`bm25s`, Snowball English stemmer, English stop words) indexes each shot's own text twice plus its ±1 neighbours' text, because speech crosses shot cuts.
  - Per-video metadata is a second BM25 index whose score is added with weight 0.3.
- **Fusion.** Reciprocal rank fusion (k = 60) of the top 1000 visual and top 1000 speech results.
- **Interaction.**
  - Keyboard-driven grid of 300 results with a group-by-video toggle.
  - Paste a screenshot (⌘V) for image search, plus "more like this" and Rocchio relevance feedback.
  - Temporal A→B queries.
  - The player loops the shot's `[start, end]`, shows the time in ms, and has a neighbouring-shot strip and an editable range.
  - Every submission goes through a confirm dialog.
  - AVS has a queue that dedupes shots, warns at more than 3 segments per video, and submits each segment separately so each gets its own verdict.
- **DRES.** Client hand-written against the official OpenAPI spec of DRES 2.0.x (`docs/dres/oas-client.json`). The flow is:
  1. `POST /api/v2/login` returns a `sessionId`.
  2. `GET /api/v2/client/evaluation/list` lists evaluations, and the client picks the ACTIVE one.
  3. `POST /api/v2/submit/{evaluationId}` sends `{"answerSets":[{"answers":[{"mediaItemName","start","end"}]}]}` with times in ms.

  The client also re-logs in on a 401, keeps a legacy `GET /api/v2/submit?item=&frame=` fallback, and logs every submission to `logs/submissions.jsonl`.

## 2. External models, datasets, services and libraries (all must be disclosed)

| Resource | Used for | Source | Licence |
|---|---|---|---|
| V3C1 sample (1,000 videos, msb, thumbnails, 480p, metadata) | corpus | course Onedata share; Rossetto et al. 2019 | Creative Commons (per video, see `license` field) |
| Whisper transcripts of V3C1 | speech search | https://zenodo.org/records/7383303 (`V3C1.zip`) | CC-BY-4.0 |
| SigLIP ViT-SO400M-14-384 (WebLI) | image/text embeddings | https://huggingface.co/timm/ViT-SO400M-14-SigLIP-384 ; Zhai et al. 2023, arXiv:2303.15343 | Apache-2.0 |
| OpenCLIP | model loading/inference | https://github.com/mlfoundations/open_clip | MIT |
| Hugging Face transformers / tokenizers | SigLIP text tokenizer | https://github.com/huggingface/transformers | Apache-2.0 |
| PyTorch (MPS backend) | inference | https://pytorch.org | BSD-3-Clause (+ bundled) |
| bm25s + PyStemmer (Snowball) | BM25 index, stemming | https://github.com/xhluca/bm25s | MIT; MIT/BSD |
| FAISS (faiss-cpu) | reference IndexFlatIP artifact | https://github.com/facebookresearch/faiss | MIT |
| FastAPI / Starlette / Uvicorn | backend | https://fastapi.tiangolo.com | MIT / BSD-3 |
| React, Vite, TypeScript | frontend | https://react.dev, https://vite.dev | MIT / MIT / Apache-2.0 |
| FFmpeg / ffprobe | format verification, selftest frame grabs | https://ffmpeg.org | GPL-3.0-or-later (Homebrew build) |
| DRES (server, OpenAPI spec) | evaluation, client spec | https://dres.dev, https://github.com/dres-dev/DRES | MIT |
| Playwright | UI end-to-end test only | https://playwright.dev | Apache-2.0 |
| Claude Code (Anthropic) | AI coding assistant used to write code and this material | https://claude.com/claude-code | commercial service |

No external API is called at query time. Everything runs locally.

## 3. Numbers

### Index sizes and build times (full corpus)

Corpus: 1,000 videos, **141,156 shots** (18 zero-length), 94,134 shots with speech (57,015 Whisper segments after filtering).
Machine: Apple M5 Pro, 48 GB RAM, PyTorch MPS.

| Artifact | Size | Build time |
|---|---|---|
| `shots.parquet` + `videos.parquet` | 4.2 MB + 0.5 MB | 5.6 s (incremental), thumbnail extraction included |
| Extracted thumbnails (`index/thumbs`) | 5.6 GB (141,156 PNGs) | (part of build_shots) |
| SigLIP image embeddings (`img_emb.f16.npy`, 141,156 × 1152, fp16) | 310 MB | 20–25 img/s, i.e. **≈ 1.6–2.0 h** for the whole corpus |
| BM25 shot transcripts / video metadata | 11.2 MB / 0.8 MB (vocab 32,722 / 18,109) | 1.8 s |
| FAISS `IndexFlatIP` (reference) | 620 MB | 0.15 s |
| Backend startup (load all + SigLIP) | 1.46 GB RSS | 8–13 s |

Raw corpus on disk: 29 GB `videos_480p`, 5.6 GB thumbnail zips, 158 MB Whisper SRT/VTT/TXT.

Note on embedding time: the build ran in three batches (20 videos at 20.0 img/s, then 718 videos, then 262 videos at 24.6 img/s).
The middle batch's logged wall time (50,180 s) is not representative: the laptop slept for hours
during it (lid closed on battery). The throughput figure (20–25 img/s, MPS fp16) is the
reproducible number. In fp32 the same model ran at 8.4 img/s.

### Query latency (`scripts/benchmark.py`)

200 queries per mode over HTTP on localhost, k = 200, full index (141,156 shots). *Server* time = in-process
time (X-Search-Ms header). *Client* time includes HTTP and JSON serialisation.

| Mode | client p50 | client p95 | server p50 | server p95 (ms) |
|---|---|---|---|---|
| visual (SigLIP text → exact IP) | 21.3 | 23.0 | 20.6 | 22.2 |
| speech (BM25) | 4.5 | 5.0 | 4.0 | 4.4 |
| fused (RRF) | 22.1 | 23.4 | 21.3 | 22.6 |
| fused, grouped by video | 22.4 | 24.7 | 21.6 | 23.7 |
| image (pasted screenshot) | 58.3 | 60.6 | 55.7 | 57.5 |
| more-like-this | 9.9 | 10.8 | 9.3 | 9.8 |
| temporal A→B | 51.6 | 53.3 | 50.8 | 52.4 |
| relevance feedback (Rocchio) | 10.0 | 10.6 | 9.3 | 9.8 |

Backend resident memory: **1,455 MB**. Every mode answers in under 61 ms at p95, so query time is
negligible compared with the time the operator spends inspecting results.

### Mock-KIS selftest (`scripts/selftest.py`)

200 random target shots (seed 42), full index. Rank of the target among 141,156 shots (depth 1000).
- **frame** is a frame grabbed from the 480p video at the shot midpoint, cropped 5%, resized to 640 px and JPEG q = 60. It mimics a KIS-V screenshot.
- **speech/fused** use 8 consecutive words of the shot's own transcript. Only 90 of the 200 targets have ≥ 8 words.

| Query | n | exact R@1 | R@10 | R@100 | MRR | ±1 shot R@10 | right video R@1 | video R@10 |
|---|---|---|---|---|---|---|---|---|
| thumbnail itself (sanity) | 200 | 0.995 | 1.000 | 1.000 | 0.998 | 1.000 | 1.000 | 1.000 |
| video frame (KIS-V proxy) | 200 | 0.635 | 0.875 | 0.960 | 0.723 | 0.915 | 0.940 | 0.980 |
| transcript words, speech mode | 90 | 0.267 | 0.689 | 0.944 | 0.418 | 0.756 | 0.944 | 0.956 |
| transcript words, fused mode | 90 | 0.067 | 0.578 | 0.900 | 0.225 | 0.689 | 0.422 | 0.933 |

Observations:
- **Image search.** A screenshot-like frame finds the right video first 94% of the time and the exact shot in the top 10 in 87.5% of cases. Most misses are adjacent shots of the same scene (±1-shot R@10 = 0.915), which the player's shot strip makes easy to correct. Going from the 20-video development set to the full 1,000 videos lowered exact R@1 only from 0.69 to 0.635.
- **Speech search** finds the right video at R@1 = 0.944. The exact shot is harder (R@1 = 0.267), because neighbouring shots share text through the ±1 window and long segments span several shots.
- **Equal-weight RRF fusion hurts spoken-word queries** (video R@1 0.42 vs 0.94 for speech-only). The visual ranking is uninformative for such queries but carries the same weight. In the UI the operator therefore chooses Speech mode for quoted speech.

## 4. Known limitations

- **One embedding per shot.** We embed only the representative thumbnail. Long shots with changing content are only reachable through that one frame.
- **Thumbnail resolution.** The 200 px thumbnails are upsampled to the model's 384 px input. Keyframes (128 GB) would give sharper embeddings but were not used.
- **Multilingual speech.** Whisper transcripts are in the spoken language, not translated. English BM25 with an English stemmer cannot match English descriptions to non-English speech.
- **Fusion.** RRF weights the visual and speech rankings equally. When a query is mostly spoken words, the visual ranking adds noise. The selftest shows fused is worse than speech-only for verbatim transcript queries, so the operator must pick the mode.
- **Temporal queries** assume B follows A within a fixed number of shots or seconds in the same video.
- **Transcript noise.** Whisper hallucinations ("Music", "You", repeated tokens, transcripts running past the video end) are filtered heuristically.
- **Selftest is a proxy.** It queries with the target's own frame or transcript words. Real KIS-V clips (projected, re-filmed) and human-written KIS-T descriptions are harder.
- **`mediaItemName` format.** The client assumes the course server uses the plain `v3cId` (e.g. `00031`). This is configurable (`MEDIA_NAME_FMT`) and must be confirmed at a practice run.

## 5. References

All authors, titles and venues below were checked against arXiv or Crossref on 2026-10-28.

- Rossetto, L., Schuldt, H., Awad, G., Butt, A. A. (2019). *V3C – A Research Video Collection*. MultiMedia Modeling (MMM 2019). arXiv:1810.04401. (Authors verified on arXiv.)
- Zhai, X., Mustafa, B., Kolesnikov, A., Beyer, L. (2023). *Sigmoid Loss for Language Image Pre-Training*. ICCV 2023. arXiv:2303.15343.
- Radford, A., Kim, J. W., Xu, T., Brockman, G., McLeavey, C., Sutskever, I. (2023). *Robust Speech Recognition via Large-Scale Weak Supervision* (Whisper). ICML 2023. arXiv:2212.04356
- Cormack, G. V., Clarke, C. L. A., Büttcher, S. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods*. SIGIR 2009. doi:10.1145/1571941.1572114
- Robertson, S., Zaragoza, H. (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. Foundations and Trends in IR 3(4). doi:10.1561/1500000019
- Rocchio, J. J. (1971). *Relevance feedback in information retrieval*. In G. Salton (Ed.), *The SMART Retrieval System*, Prentice-Hall, 313–323.
- DRES: Rossetto, L., Gasser, R., Sauter, L., Bernstein, A., Schuldt, H. (2021). *A System for Interactive Multimedia Retrieval Evaluations*. MMM 2021, LNCS. doi:10.1007/978-3-030-67835-7_33
