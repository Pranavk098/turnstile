# Turnstile — durable decisions & where truth lives

The load-bearing decisions behind Turnstile's numbers, kept short and
version-controlled so no surface has to re-derive them. For the full
methodology see `docs/METHOD.md`; for the honest boundaries, `docs/LIMITATIONS.md`.

## Project status
- **The instrument** (schema v1.1 + golden fixtures → pricing → verdict →
  detectors×10 → replay → stats → dashboard → corpus) — built, reviewed, green.
- **Real measurement** (re-pricing remedies, kind-aware divergence gate, labels
  registry, the barge-in headline + granularity/lead-cap sweeps) — done.
- **Real-data ingestion** + **explorable product UI** — done.
- **Live conversational agent** (Pipecat/WSL2, real Whisper + Piper) — done,
  with barge-in waste and open-loop preservation measured at scale.

## Honesty framing (the product's spine — never overstate)
Three tiers, labeled on every number: **Measured** (barge-in waste on real Piper;
deterministic rate-arbitrage recoverable margin 0.57%), **Instrumented-not-measured**
(voice-stack decomposition, D8 on synthetic acoustics — hypothesis + sensitivity
sweep, magnitude not claimed), **Partially-measured** (outcome-preservation, now
measured three ways and honestly kept apart: **identity** 0.985 on non-divergent
routing pivots (paid n=250, *clean-close* standard); **modeled under divergence** = None
(the real model forks in prose the label oracle can't decide); **open-loop under
divergence** — with label-elicitation the cheaper model *talked without acting* (0/0), but
with **real function-calling it acts** — but narrowly: at scale (n=72, Wilson CIs) 16.7%
registry (3/18 [5.8, 39.2]) / 4.5% judge (1/22 [0.8, 21.8]), the point falling from the
n=36 mid-read (42.9%/11.1%, overlapping CIs — consistent, not contradictory) because 36 bait
probes added divergences but zero new preserved cases; the acts concentrate in
`process_refund` (other required tools never invoked). Neither the 0 the first probe implied
nor the ~96% a naive proposal would imagine. The strict judge disagrees with the
lenient adjudicator 100% there, so 0.985 is preservation of the *clean-close* verdict,
not of problem-solving. Small n; a validated measurement + a cautionary signal, not a
fleet rate. None of it touches the deterministic margin 0.57%). Full detail:
`docs/METHOD.md`, `docs/LIMITATIONS.md`, `docs/DEMO.md`.

## Variant execution model (why 5/6 "variants" were no-ops)
Only `model_routing` is applied on the replay **backend**. Every other VariantSpec
field executes elsewhere or not at all — enforced by `turnstile_experiments.guard`
(a variant a backend can't apply raises `NotImplementedError`, never a silent
zero-delta paid no-op). Sets: `VARIANTS` (backend-executable), `REPRICING_VARIANTS`
(deterministic transform → conditional bucket, never gated proven savings),
`HARNESS_VARIANTS` (tts_chunking, measured on the barge-in harness),
`RESERVED_VARIANTS` (empty — every field now has an execution path). Source of
truth: `packages/experiments/.../variants.py`.

## Key correctness rulings still load-bearing
- **CR-B — Δcost is rate arbitrage on the ORIGINAL workload** (`replay.py`), not a
  re-price of the render (real prompts are ~4× smaller than the corpus's synthetic
  tokens → would fake savings). Real-usage Δ is a separate, non-gated companion.
- **CR-A** — the replay prompt includes the pivot turn's caller ASR (was blind).
- **Gates G1 (recorder overlap) / G2 (`chars_synthesized` = generated, never
  `len(text)`)** — `docs/GATES.md`.
- **R10 rate-key convention** — documented in `pricing/rates.yaml`.
- **Recoverable Margin** = Σ proven_savings / Σ total_cost × 100, §8.3-gated,
  reported as `[CI_lo, CI_hi]` + point + absolutes — `turnstile-prd.md` §4.3 errata.
- **Recoverable margin is a PER-DATASET figure, never a single product claim.**
  It is "the recoverable margin ON THIS fleet," and it differs by population:
  **0.57%** over the 250-trace synthetic corpus (the reproducible reference,
  README/METHOD), **1.32%** over the 23 golden fixtures (the dashboard fleet),
  **2.56%** over the 50-call realistic ingest sample — each correct on its data.
  Rule: **every surface stamps its margin with (n, dataset), and no text cites a
  different dataset's number than the one it displays.** The demo headline is the
  number for the data being shown; ultimately "your margin on your calls." The
  §8.3 gate itself lives once in `turnstile_experiments.recoverable_margin`
  (`ci_upper < 0`); `turnstile_ingest.pipeline._recoverable_margin` converged onto it.

## Where truth lives (stop re-deriving)
| Question | Authoritative source |
|---|---|
| Product methodology & limits | `docs/METHOD.md`, `docs/LIMITATIONS.md` |
| Demo/narrative script | `docs/DEMO.md` |
| Gates | `docs/GATES.md` |
| Corpus constraints | `docs/CORPUS.md` |
| Bring-your-own-calls ingestion | `docs/INGEST.md` |
| Live agent | `docs/LIVE-AGENT.md` |
| Rate table + R10 convention | `pricing/rates.yaml` |
| Variant execution model | `packages/experiments/.../variants.py` |
