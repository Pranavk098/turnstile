# LIMITATIONS — what Turnstile does not (yet) claim

Read alongside `docs/METHOD.md`. This is the deliberately unflattering list. Each
item is a *known* boundary with a stated path forward, not a surprise.

## 1. Measured outcome-preservation is not achievable on the synthetic corpus

The paid replay experiment cannot *measure* whether a cheaper model preserves the
resolution, for two reasons established on real calls (smoke #3):

- **Divergence gate is vacuous vs canned text.** Real model output vs the
  corpus's synthetic `output_text` scores ~0.04 on a 0.75 difflib gate → 100% of
  traces flagged divergent, 0 usable trials.
- **Preservation is structural (H-1).** Verdict labels ride on pinned tool
  effects, so `outcome_preserved` ≈ 1.0 by construction for tool-driven verdicts.

**Consequence:** the Tier-1 headline is the *deterministic* rate-arbitrage
recoverable margin (0.57% [0.49, 0.66]); measured preservation is **Wave-2**.

**Wave-2 path (sequenced):**
1. *(free viability check, first)* Verify the corpus's `decision_chosen` labels
   (`step_3`, `handle_billing`, `escalate`, …) form a decision vocabulary a real
   model can be reliably parsed against, and define a decision-elicitation prompt
   contract. Only if that holds does step 2 mean anything.
2. **Structured-decision divergence** — replace text-similarity with per-kind
   decision equality (route target, escalate/continue, tool name), i.e. the
   `tool_select`-sensitivity / M-2-parsing upgrade already queued as a Wave-2
   entry-criterion. Then a bounded re-smoke.
3. **Real baseline, both sides** — call a real model for the *original* decision
   too, so divergence compares real-to-real. ~2× spend + a corpus-generation
   change; follows step 2, never precedes it.

## 2. Only one of the ten remedies is replay-executable

Every `Finding` carries a `proposed_variant` the contract says the replay engine
"can execute." Today only `model_routing` is applied on the replay path. So:

- **Replay-proven (Tier-1-eligible):** D1, D5, D8 (all propose `model_routing`).
- **Detected & quantified, NOT replay-proven (Tier-2):** D2, D3, D4, D6, D7, D9,
  D10 — their remedies set reserved VariantSpec fields (`context_strategy`,
  `prefix_caching`, `retrieval_policy`, `tts_chunking`, `escalation_policy`,
  `tool_batching`) that no backend reads yet. The runner **fails loud** if asked
  to run one (`assert_variant_executable`), rather than spending on a no-op.

These are the concrete Wave-2 to-do list (`RESERVED_VARIANTS`); each maps to a
detector remedy.

## 3. The proven number is small by construction

0.57% recoverable margin is modest because only the `route` decision is rerouted,
and that is a small slice of call cost. This is honest, not a headline inflated
by counting unproven remedies. The *larger* opportunity Turnstile points at lives
in Tier-2 (voice-stack waste) — presented as a question ("do you know your
number?"), not a claim.

## 4. Corpus coverage gaps (not tuned away)

- **D2 (context bloat) and D6 (dead tokens) do not fire** on the committed
  corpus. This is a corpus *coverage* gap, stated plainly — the generator is
  **not** re-tuned to make them fire (that would be tuning-to-detectors).
- **D8 dominates (~82% of findings).** Presented as a hypothesis + sensitivity
  sweep, never calibrated down to a nicer number.

## 5. Synthetic acoustics, not real audio

D7/D8 operate on modeled inter-turn gaps and barge-in, sampled from cited
distributions. Magnitude is not claimed until the recorder emits real audio (G1),
at which point Tier-2 promotes to Tier-1 with no code change. Until then, D8
results are a *detector demonstration*, not a measurement (see `docs/GATES.md` G1).

## 6. Smaller known items

- Verdict labels `PARTIALLY_RESOLVED` / `MISROUTED` are never emitted (needs a
  scenario registry) — Wave-2.
- The LLM-judge evidence source (verdict source 5) is a real no-op pending 60
  hand labels + Cohen's κ ≥ 0.75.
- D3 covers only the doc-id-overlap half of redundant retrieval (cosine-similarity
  half deferred).
- Pricing's post-condition uses a bare `assert` (stripped under `python -O`) —
  convert to an explicit raise.
- 11 pre-existing ruff findings in `fixtures/golden/` (E741/F401) remain.

## What is solid

The instrument itself — schema → pricing → verdict → detectors(×10) → replay →
stats → dashboard — is built, reviewed, and green (566 tests), with the paid path
hardened (fail-loud guard, reproducibility manifest, trace-level resumable
checkpointing, timeout+retry, k=8 concurrency). The deterministic Tier-1 number is
reproducible from the manifest. The honesty of the *framing* is the product.
