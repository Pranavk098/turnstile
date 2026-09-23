# Demo video — recording placeholder (Track C, Day-6 P0-3)

Status: **script locked** (`docs/demo-script.md`, sha256 below); recording
**blocked on environment, not on product** — this box has no screen recorder,
no ffmpeg, no mic, and AppControl blocks bare `uvicorn`/`pytest` shims
(workaround `uv run python -m …` documented in `docs/QUICKSTART-TIMED.md`).
The live product passes its record gates (see transcript), so any machine with
a browser + recorder can execute the script as-is.

- Record WHAT: `docs/demo-script.md` shots 1–5 (~3:30), live URL
  `https://turnstile-demo.onrender.com` with the URL bar visible throughout
  (fallback: localhost:8000 — state which in the description).
- Upload WHERE: unlisted link (YouTube/Loom) → paste link here, keep this file.
- Size rule: never commit a >50 MB binary — compressed mp4/webm externally
  linked, or link-only.

```text
TODO(recording-machine): run docs/demo-script.md, upload unlisted, replace this
block with: link + duration + sha256(file or linked page) + "recorded against
[live|local], commit <sha>".
```

Script checksum (what the recording must match):

```text
sha256(docs/demo-script.md) = 85f776789b5ed232300c980a5efea1a70b7f54c3974721836b9c1ec7bc76393a
```

Record-gate transcript (2026-09-20, authorizing the shoot):

```text
live  GET /health          200 {"ok":true,"commit":"0e5d51d…"} (first hit 20 s cold = Render sleep; warm after)
live  GET /api/fleet       200 in 0.22 s, Reference fleet n=23, CPRC-loaded $0.0134
local POST /api/evaluate   cold (miss) 200 in 101.7 ms < 300 ms GREEN
local POST /api/evaluate   warm (hit)  200 in 2.9 ms < 50 ms GREEN, byte-identical (8236 B)
local GET /api/fleet       200 in 2.5 ms;  GET /home.html 200 in 80 ms (barge-in panel present)
```

Narration claims audit: ~4% barge-in → `packages/dashboard/sample/bargein.sample.json`
(4.07%, n=150); 0.57% [0.49,0.66] → `docs/METHOD.md`; 66.1 ms / 1.4 ms →
`PERF.md`; quality tiers → `fixtures/calibration/calibration_report.json`
(gate closed, 2 dims `not_measured`). No overclaim.
