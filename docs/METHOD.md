# METHOD — what Turnstile measures, and how much of it is *measured*

Turnstile instruments a voice-AI call end-to-end (ASR→LLM→tools→TTS→telephony),
prices every span from a dated rate table, adjudicates whether the call was
actually *resolved*, detects named waste classes, and attempts to *prove* each
savings claim by counterfactually replaying the call on a cheaper path.

This document is deliberately precise about the line between **proven**,
**instrumented**, and **not-yet-measured** — because the credibility of the
whole tool rests on not overclaiming.

## The number we can prove: deterministic recoverable margin

**Tier-1 (proven): routing eligible `route` decisions to a cheaper model.**

The replay engine re-prices each replaced decision as **rate arbitrage on the
original token workload** (CR-B): `price(original tokens, routed model) −
price(original tokens, original model)`, summed over replaced spans. This is
*deterministic arithmetic* against the dated rate table — it needs no live model
call, and it is 0 for any decision the variant does not reroute. The recoverable
margin is then PRD §8.3-gated (preservation ≥ 0.95 **and** the bootstrap CI upper
bound on Δcost < 0) and reported as `[CI_lo, CI_hi]` + point estimate + absolute
dollars, never a bare point estimate.

**Result (n=250, seed 0, the committed corpus):**

| Quantity | Value |
|---|---|
| Recoverable margin | **0.57% [0.49, 0.66]** |
| Proven savings (corpus) | $0.029 [0.025, 0.034] on $5.07 total spend |
| Annualized @ 1M calls | ~$126 |
| Gated variant | `model_routing_gpt5_nano` |

It is a **small, honest** number: only the `route` decision is replay-executable
today (see LIMITATIONS.md), and a route decision is a small slice of call cost.
That is the figure we stand behind.

**Real-path facts we did verify with paid calls** (smoke #3, n=30, ~$0.12 total
across debugging iterations): gpt-5-nano at `reasoning_effort="minimal"` returns
non-empty decisions at **~2s/call** and **~125 completion tokens**; a k=8
concurrent runner sustained 218 calls with no rate-limit errors. These bound the
real latency and throughput of the routed path.

## The thing we do NOT measure (and why), on a synthetic corpus

The original plan was for the **paid replay experiment** to *measure*
outcome-preservation — does the cheaper model preserve the resolution? Smoke #3
established, on real calls, that this is **not measurable on the synthetic
corpus**, for two independent reasons:

1. **The divergence gate is vacuous against canned text.** Replay compares the
   real model's output to the corpus's *synthetic* `output_text` (a generic
   placeholder like `"Let me look into that for you."`) via difflib ratio vs a
   0.75 threshold. A real reply scores ~0.04 — so **every** trace is flagged
   divergent and excluded. There is no real baseline text to match against.
2. **Preservation is structural (H-1).** Verdict labels ride on the terminal
   tool's `effect` (adjudication evidence source 1), and replay *pins* the tools.
   So `outcome_preserved` ≈ 1.0 **by construction** for tool-effect-driven
   verdicts — regardless of what the model decides. Spending real credit to
   re-measure a pinned quantity buys nothing.

Therefore **outcome-preservation is a Wave-2 measurement**, not a Tier-1 claim.
The replay experiment on synthetic data *proves the mechanism* (pinned replay,
deterministic re-pricing, §8.3 gating) but cannot *measure preservation* until it
runs against real traffic with real baselines. This corrects the earlier
"Tier-1 = measured replay" framing: on a synthetic corpus, replay is a mechanism
demonstration; the measured number requires real audio (G1) or a real-baseline
build (see LIMITATIONS.md, Wave-2).

**Divergence, when reported, is an upper bound**, not a fork rate: it measures
generator-vs-model *style* difference, not variant-induced decision change. Lead
with the verdict, not the divergence count.

## Tier-2: instrumented, not measured

The voice-stack cost decomposition and the acoustic detectors (D7 barge-in, D8
silence tax) are **mechanism demonstrated, magnitude not claimed**. D8 is ~82% of
corpus findings — presented as a **hypothesis plus a sensitivity sweep** (D8's
share moves 77.7%→85.8% as the inter-turn-gap median moves 100→450ms), never as a
bare fact. See `docs/CORPUS.md` and `.superpowers/…/sweeps-report.md`. These
promote to Tier-1 with no code change once the recorder emits real audio (G1).

## Modeling choices, stated

- **`reasoning_effort="minimal"`** on the replayed model, applied uniformly. The
  gpt-5 family are reasoning models; at a 256-token cap with default effort they
  spend the whole budget on internal reasoning and return empty content. Routing
  needs no deep reasoning, so minimal effort is the honest, consistent setting —
  not per-trace tuning.
- **Rate table** is dated with source URLs (`pricing/rates.yaml`); every run's
  manifest records its SHA-256, the git commit, the seed, the model ids, and —
  per variant — which VariantSpec fields the replay engine actually *applied*
  (the direct answer to "is this saving replay-proven?").
- **Corpus** is sampled from cited distributions and never tuned to make
  detectors fire (`docs/CORPUS.md`).

## Reproducibility

Every result JSON carries a `manifest`: git SHA, `rates.yaml` SHA-256, seed, n,
backend, corpus model ids, and per-variant applied/reserved fields. Re-running
`run_experiments.py --n 250 --seed 0` reproduces the deterministic headline
exactly (no network involved for the gated Δcost).
