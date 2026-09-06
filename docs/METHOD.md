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

**Recoverable margin is per-dataset, not a universal claim.** It is "the
recoverable margin on *this* fleet," so it differs by population: 0.57% over this
250-trace corpus, ~1.3% over the 23 golden fixtures (the dashboard fleet), ~2.7%
over the realistic ingest sample. Each is correct on its data; every surface
labels its number with `(n, dataset)`. On a real customer's traffic it is whatever
their traffic is — that is the point.

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

Therefore, **through Wave-1, outcome-preservation was not a measured claim** — and
Wave-2 has now **partially measured it on real calls** (preservation **0.985** over
non-divergent routing pivots; preservation-under-divergence still open — see the
*Wave-2 update* below). The replay experiment on synthetic data *proves the mechanism*
(pinned replay, deterministic re-pricing, §8.3 gating) but cannot *measure preservation*
via the Wave-1 lexical gate; the Wave-2 kind-aware gate is what unlocked the real-call
measurement (a full number still requires real audio (G1) or a real-baseline build for
the content-driven decisions — see LIMITATIONS.md, Wave-2).

**Under the Wave-1 lexical gate, divergence was an upper bound**, not a fork rate:
full-text `difflib` measured generator-vs-model *style* difference, not variant-induced
decision change. The Wave-2 kind-aware gate changes this — on bounded decisions it
compares parsed labels, so divergence becomes a real, measured fork rate (**7.8%** on
real routing; see below). Still lead with the verdict, not the raw divergence count.

### Wave-2 update: routing decision-identity and the first measured preservation number (real calls)

The Wave-1 gate compared full reply text (`difflib`), which nulled on real replies — a
sensible cheaper-model answer shares almost no lexical overlap with the corpus's
synthetic baseline, so **217/217** trials were marked divergent (paid, n=250/seed 8) and
the margin collapsed to a vacuous 0.00%. Wave-2 replaced it with a **kind-aware decision
gate**: for bounded-vocabulary decisions (route, tool_select, escalate_check, compose),
divergence is *label* inequality, not string distance.

Under that gate, on **real gpt-5-nano calls** (paid, n=250/seed 8, 1,734 calls):

- **A real fork rate, no longer hidden at 100%:** 17/217 routing pivots (**7.8%**)
  forked — nano genuinely chose a different route. Excluded by design (not
  re-adjudicated), as the honest gate should.
- **Decision-identity on the rest:** the 200 non-divergent pivots routed identically
  (true by gate construction).
- **The first measured preservation number:** over those 200, verdicts held at
  **0.985 (197/200)** — three flipped on utterance *content* while the routing label
  stayed identical. Preservation is no longer structurally 1.0; the mock's 1.0 is
  measured *almost* true, with three real content-driven failures.
- **Margin: 0.573% [0.481, 0.667]** (Δcost −$0.000139/trial, CI strictly negative,
  §8.3 passes). This is the **seed-8** population — compare to the **seed-8 mock
  (0.55% [0.46, 0.63])**, not the seed-0 headline. Its point rounds to ~0.57% by
  *coincidence* with the seed-0 mock headline (different populations, near-equal
  points); it does **not** "reproduce the headline."

**What this is and is not.** It measures *routing decision-identity* on the cheaper tier
and, on the non-forked trials, *verdict preservation* — under an elicitation that hands
the model the span's own candidates (for route, a 2-way `[scenario_id, "other"]` set, so
the model picks between the correct label and one alternative, not open-ended routing).
Preservation **under a divergent decision** stays unobserved: the 17 forks are excluded,
not re-adjudicated, so we have not yet watched a verdict hold or fail when the cheaper
model decides *differently*. That needs harder decisions (larger candidate sets) or a
real-baseline build — a Wave-2+ open item.

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
