# Turnstile

**A margin profiler for voice-AI agents.** It instruments a voice call end-to-end
(ASR → LLM → tools → TTS → telephony), prices every span from a dated rate table,
adjudicates whether the call was actually *resolved*, detects ten named waste
classes, and — for the one remedy it can execute — *proves* the saving by
counterfactually replaying the call on a cheaper path.

The point of the tool is **refusing to overstate.** Every number below is labeled
by how much it is actually measured.

## The headline — a number nobody has published

**~4% of TTS spend is generated, billed, and never heard.** When a caller barges in
mid-utterance, streaming TTS has already synthesized (and billed) audio the caller
never hears — because local TTS generates **~40× realtime**, so the whole readback
exists before a quarter of it has played. Measured on **real Piper synthesis** at a
cited 15% barge-in rate and a 2s buffer (the exact figure is a live measurement,
~4.1% ± run-to-run timing variance, so we say **~4%**). And it's **fixable**: chunk
the TTS finer and the waste falls — sentence→clause→word = **~4% → 2.3% → 1.2%**
(measured), at a modest synthesis-speed cost. Swept, never a single tuned figure;
the barge-in rate/position are modeled + swept, the generation-ahead is measured.

## The second number — deterministic, exact

**Recoverable margin: 0.57% [0.49, 0.66]** — routing eligible `route` decisions to a
cheaper model (gpt-5 → gpt-5-nano), computed as deterministic *rate arbitrage* on the
original token workload against the dated rate card, PRD §8.3-gated (preservation ≥
0.95 **and** bootstrap CI-upper < 0), reported with its CI and the absolute dollars
(~$126/yr at 1M calls). Exact arithmetic, reproducible from each run's manifest —
deliberately small, because `route` is the only remedy *replay-executable* today.

## Three honesty tiers

- **Measured** — the barge-in waste (real Piper) and the deterministic recoverable
  margin (exact arithmetic). Numbers we stand behind, with CIs and stated provenance.
- **Instrumented, not measured** — the rest of the voice-stack decomposition and D8
  (silence tax) on *synthetic* acoustics: mechanism demonstrated, magnitude not
  claimed. D8's ~82%-of-findings figure is a hypothesis + a sensitivity sweep, never
  a bare fact. The detector remedies (D2/D3/D4/D9/D10) carry a *conditional* saving —
  deterministic re-pricing, preservation unverified — reported in a separate bucket.
- **Not yet measured** — outcome-preservation of the cheaper model on live calls. On
  a synthetic corpus this is unmeasurable (the divergence gate compares real output to
  canned text; verdict-preservation is structural because tools are pinned; the
  corpus's caller *inputs* are placeholders). It requires real traffic — Wave-3. We do
  **not** quote a preservation rate we can't defend.

See [`docs/METHOD.md`](docs/METHOD.md) and [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
for the precise boundaries, and [`docs/DEMO.md`](docs/DEMO.md) for the walkthrough.

## The instrument

```
Trace → pricing → verdict → detectors(×10) → replay → stats → dashboard
                                    ↑ corpus + experiments feed it
```

Packages (uv workspace, under `packages/`): `schema` (frozen v1.1 contracts),
`pricing`, `verdict` (Resolution Ledger), `otel` (recorder — overlap-expressible
after the G1 redesign), `detectors` (all 10 classes), `stats`
(Wilson/bootstrap/aggregate), `replay` (credibility engine, injectable decision
backend), `corpus` (synthetic trace generator), `experiments` (baselines +
routing matrix + recoverable margin + gated OpenAI backend + D7/D8 sweeps),
`dashboard` (static, renders real re-priced data), `agent` (spike).

## Quickstart

```bash
uv sync
uv run pytest -q                     # full suite (581 tests)
```

Reproduce the deterministic headline (free — no API calls):

```bash
uv run python packages/experiments/run_experiments.py --n 250 --seed 0
```

The paid replay backend is gated hard: it refuses to run unless
`TURNSTILE_ALLOW_PAID=1` **and** `OPENAI_API_KEY` are set, and even then requires
an explicit confirmation. It measures real latency/throughput, not the deterministic
Δcost (which needs no calls). Every run writes a `manifest` (git SHA, rate-table
SHA-256, seed, model ids, and which variant fields were actually applied) so any
number is reproducible and provenance is self-describing.

## Status

The analysis instrument is complete, reviewed, and green (581 tests): the paid
path is hardened (fail-loud variant guard, reproducibility manifest, trace-level
resumable checkpointing, timeout+retry, concurrency), and the recorder expresses
the span overlap the silence-tax detector relies on. Remaining work — authored
caller utterances (to make preservation measurable), the reserved-variant
remedies, and live-agent integration for real audio — is tracked in
[`docs/superpowers/REMAINING-WORK.md`](docs/superpowers/REMAINING-WORK.md).
