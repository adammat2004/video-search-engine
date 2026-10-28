# Data formats (verified against the downloaded files)

Verified on 2026-10-28. The msb and metadata checks cover all 1,000 videos. The thumbnail, video and ffprobe checks cover the 20 videos in the `--videos 1-199` batch: 00031, 00032, 00036, 00057, 00060, 00068, 00072, 00076, 00105, 00115, 00117, 00141, 00144, 00160, 00164, 00174, 00181, 00193, 00194, 00199.

Download layout: `data/assignment2_data/` contains `msb.zip`, `videos_metadata.{json,csv,md}`, `info/<v3cId>.json`, `thumbnails/<v3cId>.zip` and `videos_480p/<v3cId>.mp4`.

## Video ids (`v3cId`)

- **5-digit, zero-padded string**, e.g. `00031`. The same form is used in every place:
  - asset file names (`videos_480p/00031.mp4`, `thumbnails/00031.zip`, `msb/00031.tsv`, `info/00031.json`)
  - the `v3cId` field in the metadata
  - shot ids inside zips (`shot00031_12.png`)
  - Whisper file names (`V3C1/00031.srt`)
- Store it as a string everywhere. Never cast it to int, which would lose the padding.
- The sample ids are sparse: ids 1–199 contain only 20 videos.

## Master shot boundaries (`msb.zip`)

- Contains `msb/<v3cId>.tsv` for all 1,000 videos.
- Header (identical in all 1,000 files): `startframe	starttime	endframe	endtime`.
- Shot `n` is **data row n, 1-based**, after the header.
- **Time unit: SECONDS** (float, up to 3 decimals). It is converted to ms for our index and for DRES (`round(t * 1000)`). The evidence:
  - The last `endtime` is within 0.5 s of the ffprobe duration for all 20 local videos. For example, 00036: 2101.899 vs 2102.172 s.
  - `endframe / fps ≈ endtime`. For example, 00031: 7689 / 23.976 = 320.70 vs 320.778.
  - `videos_metadata.md` also says "times in **seconds**".
- Totals: **141,156 data rows** across 1,000 files. There are no blank lines, no repeated headers and no malformed rows. The handout's "146,000 in the raw msb export" does not match the files.
- **18 degenerate shots**: shot 1 of 18 videos has `startframe = endframe = 0` and `endtime == starttime` (e.g. `03317` row 1: `0 0 0 0`). They are kept so row numbers stay aligned, and padded to a minimum length of 1 frame (40 ms) on submit.
- Some videos have a small constant offset: frame 0 maps to `starttime` 0.083 s in 00031. This equals that file's container `format.start_time` (0.083). It is ≤ 1 frame-ish and irrelevant to scoring. We submit the official msb times as they are.

## Thumbnails (`thumbnails/<v3cId>.zip`)

- Files sit at the zip root, named **`shot<v3cId>_<n>.png`**: PNG, **no `_RKF` suffix**, `n` matching the msb row number.
- All entries in the 20 local zips match `^shot[0-9]{5}_[0-9]+\.png$`.
- For all 20 local videos, the thumbnail count equals the TSV row count and `n` runs over exactly `1..rows`.
- Width is 200 px (per the handout and metadata).
- Keyframes (not downloaded) are documented in `videos_metadata.md` as `keyframes/<v3cId>.zip: shot<v3cId>_<n>_RKF.png`. They are unverified locally.

## Videos (`videos_480p/<v3cId>.mp4`)

- HEVC **Main** profile, level 3.0 (`L90`), `yuv420p`. Codec tag **`hvc1`**, which Safari requires (not `hev1`), so no remux is needed.
- Container brands are `isom/iso2/mp41`, and the `moov` atom comes right after `ftyp` (faststart). Audio is AAC.
- Resolution is 854×480, with some files at 640×360. Frame rates vary: 23.976, 24, 25, 29.97, 30, 50, …
- Browser support:
  - **Chrome 156** reports `canPlayType('video/mp4; codecs="hvc1.1.6.L90.B0"') = "probably"`, and MSE supports it too.
  - **Safari 26.6.2** supports HEVC `hvc1` natively on macOS.
  - Real playback and seeking in both browsers still needs a manual check (Phase 3).
  - Fallback if a browser fails: transcode to H.264 on the fly with ffmpeg.

## Metadata

- `videos_metadata.json` is a **JSON array of 1,000 objects**, sorted by `v3cId`. The CSV has the same rows.
- Fields:
  - identity: `v3cId`, `vimeoId`
  - descriptive: `title`, `description` (HTML), `tags` (`"; "`-joined string), `categories` (`"; "`-joined), `primary_category`, `top_level`, `channel`, `uploadDate`, `license`
  - technical: `duration` (seconds, int in practice), `width`, `height`, `orientation`, `shot_count`, `keyframe_count`, `thumbnail_count`
  - asset paths: `keyframes_zip`, `thumbnails_zip`, `shot_boundaries`, `video_480p`, `video_original`
  - links: `vimeo_url`, `vimeo_embed_url`
- `info/<v3cId>.json` holds the raw Vimeo metadata (here `tags` and `categories` are JSON lists). It is redundant with the array, so we use `videos_metadata.json`.
- The description has HTML tags, which are stripped before indexing.

## Whisper transcripts (Zenodo 7383303, `V3C1.zip`, CC-BY-4.0)

- `V3C1/<v3cId>.{srt,vtt,txt}` cover **all 7,475 V3C1 videos**. Ids are the same 5-digit `v3cId`, and all 1,000 sample videos are present.
- We use **SRT**: a counter line, then `HH:MM:SS,mmm --> HH:MM:SS,mmm`, then text. Times are converted to ms.
- Across the 1,000 sample videos there are 63,471 segments and about 536k words.
- **Noise**: 5,464 segments are filler (`Music`/`music` ≈ 3.8k, `...`, `.`, `?`, repeated `្`). They are dropped at indexing.
- In 288 videos the last segment ends more than 3 s past the video duration. Segment ends are clipped to the duration.
- **Transcripts are in the spoken language, not translated.** For example, 00105 is French. This limits English keyword (BM25) matching for KIS-T. It is a candidate for multilingual dense text embeddings in Phase 4.

## DRES answer format (from the handout's real text and the DRES v2 API, not the injected notes)

- An answer is `mediaItemName` (the video) plus `start` / `end` in **milliseconds**, i.e. `round(msb_seconds * 1000)`.
- The exact `mediaItemName` string the course server expects (`00031` vs `shot…` vs other) must be confirmed at the first practice run. It is configured via `MEDIA_NAME_FMT` in `.env`.
