# Corpus + experiment numbers — approach and constraints

**Decision (owner, 2026-08-31):** Synthetic trace corpus (~250 schema-valid
traces, no WSL2/live-audio) + a **real OpenAI replay backend** (the $150 credit)
for the experiment matrix. This yields genuinely measured LLM-layer numbers
while the acoustic layer stays modeled. The live acoustic agent is a later
fidelity upgrade, not a prerequisite for the demo.

## What is measured vs modeled (the tier split — see `docs/DEMO.md`)

| Layer | On the synthetic corpus | Tier |
|---|---|---|
| LLM decisions, Δcost, outcome-preservation, divergence (via **real** replay) | **measured** — real model calls | **Tier 1 (headline)** |
| ASR / TTS / telephony cost decomposition; D7 barge-in; D8 silence tax | **modeled** by the generator | **Tier 2 (mechanism, not magnitude)** |

**Promotion:** the instrument is identical; when the recorder emits real audio,
Tier-2 detectors promote to Tier 1 with no code change. Keep `docs/GATES.md`
G1/G2 live.

## Three hard constraints on the generator (it is now load-bearing)

1. **Sample, don't choose.** Turn counts, token distributions, and barge-in
   timing are drawn from **published or observed distributions**, not
   hand-picked values. Cite the source for each in the generator config. Under
   challenge, "sampled from X" survives; "I chose them" is fatal.
2. **Do not tune to the detectors.** Generate the corpus first, run the
   detectors second, report whatever comes out. Tuning the generator so
   detectors fire well turns the demo into a demo of your own assumptions.
   (Enforce culturally + by keeping generation and detection in separate,
   independently-run steps.)
3. **Barge-in rate is one named parameter, reported as a sensitivity.** Expose
   the barge-in rate as a single named config value and show D7's magnitude
   **across a plausible range of it**, so D7 is "a stated function of an input,"
   never "a claimed fact."

## Real replay backend (Tier-1 numbers)

- Implements the `DecisionBackend` protocol already defined in
  `packages/replay/backend.py` (the seam exists; MockBackend is the Wave-1
  stand-in). The real backend calls OpenAI to re-run the agent decision under
  the variant, so outcome-preservation and Δcost are observed, not assumed.
- Uses the `gpt-5 → gpt-5-mini → gpt-5-nano` tier ladder already in
  `pricing/rates.yaml`. Budget: the $150 OpenAI credit (replay re-runs only the
  decisions from turn k, and variants route to cheaper models, so cost is
  bounded well under the credit for a 6-variant × ~250-trace matrix).
- The experiment matrix + `turnstile_stats.aggregate_experiment` (already built
  and verified) produce the bootstrap CI / Wilson interval / divergence rate.
