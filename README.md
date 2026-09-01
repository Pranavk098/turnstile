# Turnstile

**A margin profiler for voice-AI agents.** It instruments a voice call end-to-end
(ASR → LLM → tools → TTS → telephony), prices every span from a dated rate table,
adjudicates whether the call was actually *resolved*, detects ten named waste
classes, and — for the one remedy it can execute — *proves* the saving by
counterfactually replaying the call on a cheaper path.

The point of the tool is **refusing to overstate.** Every number below is labeled
by how much it is actually measured.

## The headline we stand behind

**Recoverable margin: 0.57% [0.49, 0.66]** — routing eligible `route` decisions to
a cheaper model (gpt-5 → gpt-5-nano), computed as deterministic *rate arbitrage*
on the original token workload against the dated rate card, PRD §8.3-gated
(preservation ≥ 0.95 **and** bootstrap CI-upper < 0), reported with its CI and the
absolute dollars (~$126/yr at 1M calls on a $5.07-per-250-call basis). It is
exact arithmetic, reproducible from each run's manifest — and deliberately small,
because `route` is the *only* remedy that is replay-executable today.

## Three honesty tiers

- **Proven** — the deterministic recoverable margin above. Exact, gated, CI'd.
- **Instrumented, not measured** — voice-stack cost decomposition and the acoustic
  detectors (D7 barge-in, D8 silence tax). The mechanism is demonstrated; the
  *magnitude* is not claimed on synthetic acoustics. D8's ~82%-of-findings figure
  is presented as a hypothesis plus a sensitivity sweep, never a bare fact.
- **Not yet measured** — outcome-preservation of the cheaper model. On a synthetic
  corpus this is unmeasurable (the divergence gate compares real output to canned
  text; verdict-preservation is structural because tools are pinned; and the
  corpus's caller *inputs* are placeholders). It requires real utterances, then
  real traffic — Wave-2. We do **not** quote a preservation rate we can't defend.

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
