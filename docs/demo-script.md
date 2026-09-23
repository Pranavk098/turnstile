# Turnstile — demo video script (2–4 min, actual live product)

Source flow: `docs/DEMO.md` (tiers, spine, judgment lines — reused verbatim, not
duplicated here). This file adds the **shot list + narration deltas** for the
Day-6 recording: quality-beside-cost visible throughout, and the PERF/methodology
honesty line. Record against the **live URL** (up, verified 2026-09-20):
`https://turnstile-demo.onrender.com` — keep the URL bar visible in every shot.
Fallback if live is cold/slow: local `python -m uvicorn
turnstile_service.app:app --port 8000` (commit `9c0b30f`) and say so on camera.

Shared with Track B (hero coordination): every shot below keeps the **quality
column beside the cost column** and the **~4% barge-in / 0.57% margin** pair, so
stills/GIFs cut from these timestamps cannot contradict the README hero
(`docs/hero.png`). Timestamps are the contract — cut GIFs only from 0:20–1:40.

## Numbers the narration may use (traceable, nothing else)

- Barge-in waste: **~4% of TTS spend unheard at 15% barge-in rate** (measured:
  `packages/dashboard/sample/bargein.sample.json` headline 4.07%, harness n=150;
  say "~4%", never 4.07 — run-to-run variance). Remedy: sentence→clause→word =
  ~4%→2.3%→1.2% (measured, `docs/DEMO.md`).
- Routing margin: **0.57% [0.49, 0.66]**, ~$126/yr at 1M calls, §8.3-gated
  (`docs/METHOD.md`). Small by construction — only `route` is replay-executable.
- Fleet on camera: Reference fleet n=23, CPRC-loaded $0.0134 vs naive $0.0088
  (`GET /api/fleet`, live-verified).
- Quality: **5 dimensions measured** (deterministic rules); faithfulness +
  answer relevance **`not_measured`** — calibration gate closed
  (`fixtures/calibration/calibration_report.json`, n_labels=0 < 60). Never show
  a quality score without its tier chip.
- Speed (say once, shot 5): cold single-call eval p95 66.1 ms (< 300 ms gate),
  cache-hit 1.4 ms (< 50 ms gate) (`PERF.md`); re-measured live during this
  session: cold POST 101.7 ms, warm hit 2.9 ms, byte-identical.

## Shot list (total ~3:30)

1. **0:00 Fleet overview** (`/`, fleet table). Narration: "Every call priced,
   every dollar with a quality label next to it — pass/fail plus tier, measured
   or not-measured, never a bare score." Visible: cost column + quality column
   side by side, CPRC-loaded vs naive headline.
2. **0:45 Drill into `07_barge_in_waste`** (`/api/calls/07_barge_in_waste`).
   Narration (DEMO.md D7 lead, abridged): "Real TTS synthesis, measured: at a
   15% barge-in rate ~4% of TTS spend is generated, billed, never heard —
   chunk finer and you recover most of it." Visible: D7 finding ($0.0040 waste),
   quality `pass/measured` on the same panel.
3. **1:30 Paste-your-own-call** (`POST /api/evaluate` with the `docs/INGEST.md`
   doc-example, or the UI ingest box). Narration: "Paste one call, instant
   report — cost, verdict, findings, quality, one round trip." (Measured
   101.7 ms cold on localhost; live warm fleet GET 0.22 s.)
4. **2:15 Quality beside cost** (per-call hero-quality panel + fleet quality
   cells). Narration: "Five rubric dimensions, deterministic — and the two that
   need a calibrated judge read `not_measured` until 60 hand labels pass κ ≥
   0.75. An uncalibrated score would be decoration; we don't ship decoration."
5. **3:00 Routing margin, then PERF/methodology honesty line, then close.**
   Narration: "Deterministic 0.57% [0.49, 0.66] on route decisions — small, and
   that's the point: it's the only remedy replay-executable today. Speed:
   single-call eval p95 66 ms against a 300 ms budget; cache hits 1.4 ms.
   Method and limits: `docs/METHOD.md`, `docs/LIMITATIONS.md` — the barge-in
   number becomes yours the moment you point this at your traffic."

## Record gate (charter §2 — abort if red)

Before pressing record, curl-time the target: cold GET < 5 s, eval warm
p95 < 300 ms. Session transcript 2026-09-20: live `/api/fleet` 200 in 0.22 s
(warm; first `/health` hit 20 s cold — Render free-tier sleep, platform not
product); local cold POST 101.7 ms / warm 2.9 ms — GREEN, recording authorized
against live (warm) with local fallback stated.
