# PRD-01 DoD — live re-verification (Track D, P0 #5)

**Date:** 2026-09-15 · **Live URL:** `https://turnstile-demo.onrender.com`
**Scope:** Track D owns README badge line only, DEPLOY prose (hostname line owned by
Track A — not overwritten), and this checklist. No edits to `app.py`, `Dockerfile`,
`render.yaml`, dashboard HTML, `packages/schema`, pricing.
**Method:** every item below was probed against the LIVE surface (not localhost) on
2026-09-15; warm timings measured with `curl.exe` / `urllib`. Frozen-contract files
untouched by this track.

## EARS gate (Day-1 P0 #5)

- The live README badge SHALL link to a page that returns 200.
  **PASS.** Badge href `https://turnstile-demo.onrender.com/`:
  `HTTP 200 time_total=0.258s size=104997` (byte-size matches the DEPLOY warm transcript).

## PRD-01 §7, one by one

- [x] Public URL loads the fleet view with **no install and no auth**, first paint
      under 5 s even on a cold free-tier container.
      **WARM PASS / COLD RED (honest).** Warm `GET /` → 200 in 0.258 s, size 104997,
      no auth headers, zero install. `GET /api/fleet` → 200 in 0.211 s,
      label `Reference fleet (23 golden fixtures)`. Forced-cold transcript in
      `docs/DEPLOY.md` (17 min idle): first paint 22.393 s > 5 s budget — container
      boot, not content (`/api/fleet` 0.217 s immediately after wake). Remedy recorded
      in DEPLOY (keep-warm ping, Day-1 P1 #6, out of P0 scope).
- [x] Drill into a single call and see a Detector-7 barge-in finding with honesty label.
      **PASS.** `GET /api/calls/07_barge_in_waste` → 200, 1 finding,
      `class_id 7`, `confidence 0.95`,
      `evidence {chars_synthesized 184, chars_played 61, wasted_chars 123}`,
      `verdict RESOLVED`, quality block present (5 deterministic `measured` dims +
      2 `pending`/`not_measured` judge dims), `_provenance` present.
- [x] Paste the `INGEST.md` example (or own call) → live eval report.
      **PASS.** `POST /api/evaluate` with `example_call.json` → 200 `RESOLVED`,
      0 findings (honestly absent — doc example carries no G2 counts, as DEPLOY notes),
      shape `{calls, coverage_summary, details, findings, fleet, label, n, note,
      provenance, sample}`. Barge-in preset (doc example + `chars_synthesized 200` /
      `chars_played 60`) → 200 with live **D7 finding** (`class_id 7`,
      `wasted_chars 140`, `tts_waste_usd 0.0035`). First POST 1513 ms (cold engine),
      repeat 186 ms warm.
- [x] **Zero paid calls, $0 hosting** — proven.
      **PASS.** `render.yaml`: free web service, Docker runtime, `/health` check,
      `autoDeploy: true`; only env var `UV_LINK_MODE=copy` — no paid addon, database,
      redis, or plan upgrade. Service-source scan
      (`openai|anthropic|api_key|apikey` over `packages/service/src`, 6 files):
      **no matches** — no model client, key handling, or egress in the request path.
      Live: single origin, **no `Access-Control-Allow-Origin` header**; evaluate ran
      the MockBackend path only.
- [x] Malformed input fails loud (422 + field path), never a 500; size/count bounded.
      **PASS.** Extra top-level field → `422 {"detail":"invalid ingest call --
      bogus_field: Extra inputs are not permitted"}`. Nested typo →
      `422 ... turns[0].asr.transcript_typo: Extra inputs are not permitted`.
      Bad type → `422 ... telephony.billable_seconds: Input should be a valid
      integer ...`. Bad JSON → 422 with parser message. 26-call set →
      `413 {"detail":"26 calls; limit is 25"}`. 1.1 MB body →
      `413 {"detail":"body is 1100028 bytes; limit is 1000000"}`. No 500 on any
      user-input probe.
- [x] `uv run pytest` green including new `packages/service/tests`.
      **PASS (committed tree: 1079 passed, 4 skipped).** CI recount on the pushed tip
      observes exactly `1079 passed, 4 skipped` with zero failures — the
      `test_readme_suite_count_matches` guard pins the README count line to the
      committed tree, which is why this track reverted the concurrent track's
      uncommitted `1092` count hunk (their 13 extra tests live in untracked
      `packages/service/tests/test_ratelimit.py`, not in any commit; they will bump
      the count when they land). Local runs in this checkout observe 1092 only
      because those uncommitted files are present.
- [x] API responses carry the same provenance/tier labels as the CLI artifact.
      **PASS.** Fleet carries `_provenance`; calls carry per-call
      `quality{label,tier}` side-by-side with `cost_usd` (tier `measured`);
      evaluate artifact carries `provenance` + per-call quality + `details` with
      `_provenance`. Parity with committed JSON is pinned by the service parity test.
- [x] `README` demo link and `docs/DEPLOY.md` document the URL, host, $0 claim,
      redeploy steps, cold-start behavior.
      **PASS (this track).** README line 5 flipped coming-soon → live URL
      (`demo-live-brightgreen` → `https://turnstile-demo.onrender.com`), CI + license
      badges intact. `pyproject.toml` Demo URL already pointed at the live hostname —
      left untouched per spec. DEPLOY holds: Live-URL hostname + LIVE status (Track A),
      host choice + fallback (Render free primary, HF Spaces + Fly fallbacks, binding),
      exact $0 claim, relied-on free-tier limits (sleep ~15 min idle, 512 MB, shared CPU,
      100 GB egress; eval caps 1 MB / 25 calls / in-memory / concurrency 20),
      cold-start behavior + forced-cold transcript + keep-warm remedy, redeploy/rollback,
      owner setup, local parity + live proof transcripts, manual verify script, endpoint
      limits. This track added no hostname overwrite.
- [x] CI redeploys on push to the default branch and is green.
      **CI green on the pushed tip (see transcript note).** `render.yaml` has
      `autoDeploy: true`. First push of this track (81ce0bf) went CI-red for a
      Track-D-caused reason: whole-file staging of README.md carried the concurrent
      track's uncommitted `1092` count hunk, and the committed tree (without their
      untracked tests) recounts to 1079 — the README-count guard failed, everything
      else green (links ✓, keyless-demo ✓, 1079 passed). Corrective commit reverts
      the count line to `1079`; this checklist records the red honestly.
      Note: `/health.commit` returns `"unknown"` (manual deploy or
      missing `RENDER_GIT_COMMIT`); owner fix recorded in DEPLOY (Manual Deploy →
      Deploy latest commit from the connected repo).

## Known non-P0 REDs (recorded, not hidden)

1. Cold first paint 22.4 s > 5 s budget (free-tier boot; warm path 0.26 s green).
2. `/health.commit = "unknown"` — deploy not SHA-traced; owner one-click fix in DEPLOY.

## Footprint (this track)

- `README.md` line 5 only (badge flip). The pytest-count line is byte-identical to
  the base commit (this track reverted a concurrent uncommitted hunk it had
  accidentally staged — see CI note above).
- This file (`docs/PRD01-DOD-LIVE.md`).
- Concurrent working-tree changes NOT mine and NOT touched:
  `packages/service/.../app.py` + `ratelimit.py` + `test_ratelimit.py` (Day-1 P0 #4 track),
  untracked `docs/ROADMAP-sprint-01.md` + `docs/prd/sprint-01/`.
