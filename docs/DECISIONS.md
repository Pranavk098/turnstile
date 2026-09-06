# Turnstile — durable decisions, boundaries & where truth lives

**Why this file exists (audit Task-1, HIGH finding):** the working ledger
(`.superpowers/sdd/.../progress.md`) is **not in git** — it is local to one
machine and invisible to GLM's separate clone. This file is the version-controlled
extract of the load-bearing decisions and boundaries every session (Claude or GLM)
must respect. It is short on purpose; it is not a re-transcription of the ledger.

## Lane boundaries (HARD — do not cross)
- **`packages/schema/` and `fixtures/golden/` are owner+Claude ONLY.** GLM must not
  edit them. A change that seems to need one → STOP and flag.
- **Contract changes, demo/product narrative, and anything that spends OpenAI
  credit** stay with owner/Claude. GLM never triggers a paid run.
- GLM owns implementation in its lanes (currently `experiments`, `replay`, `agent`,
  `dashboard`, and any new Wave-3 packages) via `opencode/*` branches; **Claude
  reviews + merges** every branch. Briefs live in `docs/superpowers/briefs/` so
  GLM's clone can fetch them.

## Delegation model
Delegate the bulk of implementation to GLM (OpenCode, separate clone
`C:\Users\prana\turnstile-oc`, shares refs). Claude decides, writes
acceptance-criteria'd briefs, reviews diffs, and merges. Discipline carried into
every brief: stated/swept models, measure-first, **STOP-and-flag** on any modeling
decision, no silent no-ops, each branch ends green + `ruff check packages/` clean.
See `memory/turnstile-delegation-model.md`.

## Wave status
- **Wave 0** (schema v1.1 + golden fixtures) — DONE.
- **Wave 1** (the instrument: pricing, verdict, detectors×10, replay, stats,
  dashboard, corpus, otel) — DONE.
- **Wave 2** (real measurement: re-pricing remedies, verdict fixes, D3 cosine,
  labels registry, the barge-in headline + lead_cap/granularity sweeps, drift
  applied) — DONE.
- **Wave 3** (owner-chosen 2026-09): **W3-A real-data ingestion** + **W3-B
  explorable product UI**. Live conversational agent (Pipecat/WSL2) deliberately
  deferred. Demo video dropped in favour of a live product walkthrough.

## Honesty framing (the product's spine — never overstate)
Three tiers, labeled on every number: **Measured** (barge-in waste on real Piper;
deterministic rate-arbitrage recoverable margin 0.57%), **Instrumented-not-measured**
(voice-stack decomposition, D8 on synthetic acoustics — hypothesis + sensitivity
sweep, magnitude not claimed), **Not-yet-measured** (outcome-preservation — the
synthetic corpus can't measure it: canned outputs + placeholder caller inputs +
tool-pinned verdicts are structural, H-1). Full detail: `docs/METHOD.md`,
`docs/LIMITATIONS.md`, `docs/DEMO.md`.

## Variant execution model (why 5/6 "variants" were no-ops)
Only `model_routing` is applied on the replay **backend**. Every other VariantSpec
field executes elsewhere or not at all — enforced by `turnstile_experiments.guard`
(a variant a backend can't apply raises `NotImplementedError`, never a silent
zero-delta paid no-op). Sets: `VARIANTS` (backend-executable), `REPRICING_VARIANTS`
(deterministic transform → conditional bucket, never gated proven savings),
`HARNESS_VARIANTS` (tts_chunking, measured on the barge-in harness),
`RESERVED_VARIANTS` (empty). Source of truth: `packages/experiments/.../variants.py`.

## Key correctness rulings still load-bearing
- **CR-B — Δcost is rate arbitrage on the ORIGINAL workload** (`replay.py`), not a
  re-price of the render (real prompts are ~4× smaller than the corpus's synthetic
  tokens → would fake savings). Real-usage Δ is a separate, non-gated companion.
- **CR-A** — the replay prompt includes the pivot turn's caller ASR (was blind).
- **Gates G1 (done: recorder overlap) / G2 (`chars_synthesized` = generated, never
  `len(text)`)** — `docs/GATES.md`.
- **R10 rate-key convention** — documented in `pricing/rates.yaml`.
- **Recoverable Margin** = Σ proven_savings / Σ total_cost × 100, §8.3-gated,
  reported as `[CI_lo, CI_hi]` + point + absolutes — `turnstile-prd.md` §4.3 errata.

## Where truth lives (stop re-deriving)
| Question | Authoritative source |
|---|---|
| Current state / next actions | `HANDOFF.md` (keep it stamped — see its top) |
| Product methodology & limits | `docs/METHOD.md`, `docs/LIMITATIONS.md` |
| Demo/narrative script | `docs/DEMO.md` |
| Gates | `docs/GATES.md` |
| Corpus constraints | `docs/CORPUS.md` |
| Rate table + R10 convention | `pricing/rates.yaml` |
| Variant execution model | `packages/experiments/.../variants.py` |
| Full session narrative (local, unversioned) | `.superpowers/sdd/.../progress.md` |
