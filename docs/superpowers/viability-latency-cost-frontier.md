# Wave-2 Item — latency–cost frontier viability check

**Author:** GLM (opencode) · **Date:** 2026-09-04 · **Cost:** $0.00 (no API
calls; local analysis only) · **Origin brief:**
`docs/superpowers/briefs/glm-overnight-batch-2.md` §T2 · **Gate:** no build
work starts until the owner reviews this note.

---

## Verdict: GO — one lever qualifies, with exactly one stated modeling decision

**The lever: model tier at the decision boundary (route→nano), with the
measured latency ratio carried into the trace's wall-clock arithmetic.** It
is the only candidate the instrument already prices *both* sides of:

* **Latency axis — measured, zero new spend.** Smoke #3 (owner-run, n=30,
  ~$0.12, recorded in `docs/METHOD.md:38-47` and
  `packages/experiments/src/turnstile_experiments/openai_backend.py:54-61`)
  measured the joint small-model + minimal-reasoning config at **~2s/call vs
  ~9s** for the default config on the same prompt. Those measurements are in
  the repo; the frontier needs no new paid calls.
* **Model-$ axis — priced.** `pricing/rates.yaml` (gpt-5 1.25/10.00 vs
  gpt-5-nano 0.05/0.40 per Mtok); the gated rate-arbitrage machinery in
  `turnstile_replay` already computes this Δ exactly (the 0.57% number).
* **Telephony-seconds axis — priceable with ONE stated remap.**
  `pricing/rates.yaml` bills telephony per billable minute and the corpus
  derives billable seconds from turn wall time (`generate.py:488`); turn
  walls are built from the spans' own durations. Replacing a decision's
  `latency_ms` by `measured_ratio × latency_ms` and letting the trace's wall
  arithmetic follow (1:1) prices the telephony side deterministically.

**The one modeling decision (flagged, stated, swept — never a single tuned
figure):** the latency remap. The corpus's synthetic decision latencies are
0.3–0.9s (`generate.py:67 LLM_LATENCY_MS_RANGE = (300, 900)`) — an order of
magnitude below the real measured scale — so an additive delta remap
(−7s/decision) would drive walls negative and is incoherent. The proposal is
a **ratio remap** in proportionate space (new = old × measured_ratio ≈ 2/9 ≈
0.22), swept over a band (0.10 / 0.22 / 0.40) that covers the measurement's
uncertainty rather than asserting the point estimate. Everything downstream
(walls, telephony billable seconds) follows the trace's own arithmetic — no
second assumption.

**What moves on each axis (the frontier):**

| Axis | Direction | Source | Status |
|---|---|---|---|
| Mean decision latency | ↓ by the swept ratio (center ~78%) | measured ratio (smoke #3) applied to trace latencies | measured input + stated remap |
| Model/TTS $ | ↓ (cheaper tier; arbitrage already gated) | `rates.yaml` via existing rate arbitrage | priced |
| Telephony seconds | ↓ 1:1 with the wall shrink the remap produces | trace wall arithmetic → `generate.py:488` convention | priced via the stated remap |
| Outcome preservation | unmeasured | divergence gate exists; preservation beyond label-equality is Wave-2 | **out of scope — the honest boundary** |

**Why the other candidates were rejected:**

* **TTS buffer lead** (`sim.py:48 DEFAULT_LEAD_CAP_S`): the harness measures
  the *waste* side (the 4.11%→4.67% sweep) but the cost of a smaller buffer
  is underrun/stall risk — dead air, longer calls — which nothing in the
  repo prices. Using it would require inventing a stall model: a second
  modeling decision on top of a first, violating this task's "cleanest
  lever" bar.
* **Reasoning effort alone:** smoke #3 varied tier and effort *together*
  (nano + minimal vs default), so no isolated per-lever latency measurement
  exists, and isolating them needs new paid calls — prohibited this batch.
  The joint config is exactly what the `model_routing` knob executes for the
  $ side, so the lever is scoped as the joint config, honestly labeled.

## §1 What the sweep would run (proposal — no code written)

1. Corpus: the standard `generate_corpus(n, seed)` (reference n=250, seed 0),
   priced as always.
2. Variant: `model_routing={"route": "gpt-5-nano"}` (the gated matrix
   variant), replayed via the existing MockBackend path (no spend).
3. Remap: every replayed decision's `latency_ms` × swept ratio; turn walls
   and telephony billable seconds recomputed by the trace's own rules.
4. Sweep: ratio ∈ {0.10, 0.22, 0.40} × scope ∈ {route-kind decisions only,
   all decisions}. Same seed at every point (caller behavior shared).
5. Report per point: mean decision latency ↓, model-$ Δ (the gated
   arbitrage figure, unchanged), telephony-$ Δ (the remap's product), net
   total-$ Δ with the existing bootstrap CI — each axis labeled measured /
   priced / remapped. The labeled output makes the frontier readable without
   letting the remapped telephony figure masquerade as measured.

## §2 The honest caveats the writeup must carry

* The corpus's latency scale is synthetic (`LLM_LATENCY_MS_RANGE`); the
  remap moves *relative* latency, and absolute seconds in the output are
  synthetic-scale — the same caveat replay.py already states for the
  real-usage companion figure (CR-B).
* The telephony saving is a *modeled consequence* of the stated remap, not a
  measured call-duration delta — it must never be presented alongside the
  gated 0.57% without that label.
* Preservation (does the cheaper/faster config still resolve the call?) is
  the real-world trade this instrument cannot price yet — that is the
  frontier's missing axis and the reason Wave-2's structured-divergence work
  exists.

## §3 Suggested one-line addition for docs/LIMITATIONS.md (owner to fold)

> "The latency–cost frontier (if built) reports a *modeled* telephony side:
> decision-latency reductions are a measured ratio (smoke #3) applied to the
> synthetic corpus's latency scale, and telephony seconds follow the trace's
> own wall arithmetic 1:1. It is not a measured call-duration delta."

---

**Stopping here per the brief.** Deliverable complete: this note (verdict,
both priced axes, the flagged remap, the proposed sweep). Zero code was
changed; no spend was incurred.
