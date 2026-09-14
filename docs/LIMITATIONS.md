# LIMITATIONS — what Turnstile does not (yet) claim

Read alongside `docs/METHOD.md`. This is the deliberately unflattering list. Each
item is a *known* boundary with a stated path forward, not a surprise. The honesty
of the framing is the product; this file is where that honesty is kept honest.

## 1. Everything is measured on synthetic or small data — no real fleet yet

The reference corpus (250 traces) is generated. The live-agent caller is a
*scripted* synthetic caller. The realistic ingest sample is real in *shape* but
small (50 calls). **No real customer fleet has been run through Turnstile.** Every
headline is therefore "the number on *this* data," and the corpus is deliberately
not tuned to make detectors fire. The single highest-value next step is pointing
the instrument at real traffic — at which point the deterministic margin, the
voice-stack waste, and the preservation number all become "your number on your
calls." Until then, read every figure as a demonstration on known data.

## 2. Measured outcome-preservation is small-n and narrow

Preservation is measured three ways and kept apart (see METHOD), and none is a
fleet rate:
- **Identity preservation 0.985** (paid n=250) is preservation of the *clean-close*
  verdict on *non-divergent* routing pivots — not of problem-solving, and not under
  divergence.
- **Open-loop preservation-under-divergence** with real function-calling is
  **16.7% registry / 4.5% judge** at n=72 (22 divergent) — wide Wilson CIs, and the
  acts concentrate almost entirely in `process_refund` (other required tools were
  never invoked). A validated measurement and a cautionary signal, not a fleet rate.
- **Modeled-under-divergence** is `None`: the real model forks in prose the label
  oracle cannot decide.

Path forward: larger n, more scenarios, and ultimately real caller utterances — the
synthetic corpus's caller side is placeholder text, so a decision label is not
inferable from it even by a perfect model.

## 3. The proven margin is small by construction

0.57% recoverable margin is modest because only the `route` decision is rerouted,
and that is a small slice of call cost. Only `model_routing` yields **gated proven
savings** on the replay backend. The other remedies execute elsewhere and are never
folded into the gated number: the re-pricing remedies (`context_strategy`,
`prefix_caching`, `retrieval_policy`, `tool_batching`, `escalation_policy`) report a
**conditional** saving in a separate bucket (their outcome-preservation is
unverified on the synthetic corpus, H-1), and `tts_chunking` is a **measured**
result on the barge-in harness with its own CIs. This is honest, not a headline
inflated by counting unproven remedies. The *larger* opportunity Turnstile points at
lives in the voice-stack waste — presented as a question ("do you know your
number?"), not a claim.

## 4. D8 rests on modeled gaps, not recorded audio

D7 (barge-in waste) is now measured on **real Piper audio at volume** (n=200,
synthesized-minus-played from real accounting, never `len(text)`). D8 (the silence
tax) is different: it rests on inter-turn and processing gaps **sampled from cited
distributions** (Stivers 2009; a Telnyx processing-latency benchmark), not recorded
from real calls. It is presented as a hypothesis plus a sensitivity sweep, never as
a bare fact, and is not calibrated down to a nicer number. Real recorded call audio
would promote it the way it promoted D7.

## 5. Corpus coverage gaps (not tuned away)

- **D2 (context bloat) and D6 (dead tokens) do not fire** on the committed corpus.
  This is a corpus *coverage* gap, stated plainly — the generator is **not**
  re-tuned to make them fire (that would be tuning-to-detectors).
- **D8 dominates (~82% of corpus findings).** Presented as a hypothesis + sweep.

## 6. Smaller known items

- The **LLM-judge evidence source** (verdict source 5) stays a deliberate no-op
  pending 60 hand labels + Cohen's κ ≥ 0.75; the strict-judge figures reported today
  come from a separate probe, kept apart from the adjudicator's verdict.
- **D3's cosine-similarity half** is implemented but **inert** unless a local
  embedding model is available; the doc-id-overlap half is the always-on path.

## What is solid

The instrument itself — schema → pricing → verdict → detectors(×10) → replay →
stats → dashboard → ingest → live agent — is built, reviewed, and green (942 tests),
with the paid path hardened (fail-loud guard, reproducibility manifest, resumable
checkpointing, timeout+retry, k=8 concurrency). The deterministic Tier-1 number is
reproducible from the manifest. The honesty of the *framing* is the product.
