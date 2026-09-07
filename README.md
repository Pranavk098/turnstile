# Turnstile

**A margin profiler for voice-AI agents.** It instruments a voice call end-to-end
(ASR → LLM → tools → TTS → telephony), prices every span from a dated rate table,
adjudicates whether the call was actually *resolved*, detects ten named waste
classes, and — for the one remedy it can execute — *proves* the saving by
counterfactually replaying the call on a cheaper path.

The point of the tool is **refusing to overstate.** Every number below is labeled
by exactly how much it is actually measured — Measured, Instrumented-not-measured,
or Modeled — and no surface ever quotes a stronger number than it can defend.

## The headline — a number nobody has published

**~4% of TTS spend is generated, billed, and never heard.** When a caller barges in
mid-utterance, streaming TTS has already synthesized (and billed) audio the caller
never hears — because local TTS generates **~40× realtime**, so the whole readback
exists before a quarter of it has played. Measured on **real Piper synthesis** at a
cited 15% barge-in rate and a 2s buffer (~4.1% ± run-to-run timing variance, so we
say **~4%**). And it's **fixable**: chunk the TTS finer and the waste falls —
sentence→clause→word = **~4% → 2.3% → 1.2%** (measured), at a modest synthesis-speed
cost. Swept, never a single tuned figure.

## The second number — deterministic, exact

**Recoverable margin: 0.57% [0.49, 0.66]** (n=250, seed 0) — routing eligible `route`
decisions to a cheaper model (gpt-5 → gpt-5-nano), computed as deterministic *rate
arbitrage* on the original token workload against the dated rate card, §8.3-gated
(preservation ≥ 0.95 **and** bootstrap CI-upper < 0), reported with its CI and the
absolute dollars (~$126/yr at 1M calls). Exact arithmetic, reproducible from each
run's manifest — deliberately small, because `route` is the only remedy
*replay-executable* today. Recoverable margin is **per-dataset**, never a universal
claim: 0.57% over the corpus, ~1.3% over the golden fixtures, ~2.7% over the ingest
sample — each labeled with its `(n, dataset)`.

## The third number — measured on real model calls

The deterministic margin assumed the cheaper model would make the same decisions.
**Wave-2 replaced the assumption with a measurement.** A kind-aware divergence gate
compares the *decision* the cheaper model makes (its parsed label), not the raw text,
and paid replay ran the real `gpt-5-nano` over the corpus (n=250, seed 8, 1,734 calls,
~$0.39):

- **Margin 0.573% [0.481, 0.667]** — the deterministic number reproduced with a real
  model actually deciding (compare to the seed-8 mock's 0.55%, its own population).
- **A real 7.8% fork rate** (17/217) — the cheaper model genuinely routed some calls
  differently. The old full-text gate hid this as a flat 100%-divergent null; the
  decision gate surfaces it as a real, measured rate.
- **The project's first measured preservation number: 0.985** (197/200 non-divergent
  pivots) — three verdicts flipped on utterance *content* while the routing decision
  held. Preservation is no longer structurally 1.0; it is a number, with three real
  failures.

**What that is and is not.** It measures *routing decision-identity* and, on the
non-forked calls, *verdict preservation* — under an elicitation that hands the model
the span's own candidates (for `route`, a 2-way `[scenario_id, "other"]` choice).
Preservation **when the model decides differently** stays unobserved: the 17 forks are
excluded, not re-adjudicated (re-adjudicating a fork through pinned tools would judge a
call that never happened). A registry-grounded **oracle** for that case is built and
reported as a strictly *separate, modeled* figure — never folded into the measured
0.985 — and the real measured answer needs open-loop execution of the divergent path
(a live agent), which is deferred and named as the honest ceiling.

## Three honesty tiers

- **Measured** — barge-in waste (real Piper); the deterministic recoverable margin
  (exact arithmetic); and now, on real model calls, the 7.8% fork rate and 0.985
  verdict preservation over non-divergent pivots. Numbers we stand behind, with CIs
  and stated provenance.
- **Instrumented, not measured** — the rest of the voice-stack decomposition and D8
  (silence tax) on *synthetic* acoustics: mechanism demonstrated, magnitude not
  claimed. D8's ~82%-of-findings figure is a hypothesis + a sensitivity sweep, never a
  bare fact. Detector remedies (D2/D3/D4/D9/D10) carry a *conditional* saving —
  deterministic re-pricing, preservation unverified — in a separate bucket.
- **Modeled / not-yet-measured** — preservation *under a divergent decision*. The
  oracle estimates it from ground-truth intent, but on the current corpus every route
  fork is registry-undecidable (the 2-way candidate set), so it honestly returns *no
  number*; the real measurement is open-loop execution (deferred). We never quote a
  preservation-under-divergence rate we can't defend.

See [`docs/METHOD.md`](docs/METHOD.md) and [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)
for the precise boundaries, [`docs/DECISIONS.md`](docs/DECISIONS.md) for the durable
decisions, and [`docs/DEMO.md`](docs/DEMO.md) for the walkthrough.

## See it — the explorable dashboard

The dashboard is a self-contained, offline editorial report of real re-priced data —
a fleet overview, per-call drill-down (flame graph, findings, verdict), and a source
switch between the golden fixtures and a **real-format ingest** sample. It shows the
acoustic detectors (D6/D7/D8) **absent — no data for this input** where a log lacks
the acoustic fields, never a fake $0. One command builds the data and serves it:

```bash
make demo          # builds the dashboard data, then serves it at localhost:8000
# then open http://localhost:8000/home.html  (the guided tour: home → fleet → call → ingest)
```

Or without make:

```bash
uv run python packages/dashboard/build_data.py
cd packages/dashboard && uv run python -m http.server 8000
```

**Point it at your own calls:** the `ingest` package maps a real voice-AI call-log
format to the v1.1 `Trace` so the whole pipeline runs on non-synthetic data — see
[`docs/INGEST.md`](docs/INGEST.md).

## The instrument

```
Trace → pricing → verdict → detectors(×10) → replay → stats → dashboard
              ↑ corpus + ingest + experiments feed it
```

Packages (uv workspace, under `packages/`): `schema` (frozen v1.1 contracts),
`pricing`, `verdict` (Resolution Ledger + the fork oracle), `otel` (overlap-capable
recorder), `detectors` (all 10 classes), `stats` (Wilson/bootstrap/aggregate),
`replay` (credibility engine, injectable decision backend, kind-aware divergence
gate), `corpus` (synthetic trace generator), `ingest` (real call-log → Trace),
`experiments` (baselines + routing matrix + recoverable margin + gated OpenAI backend
+ preservation harness + D7/D8 sweeps), `dashboard` (static, renders real re-priced
data), `agent` (the real barge-in harness behind the Tier-1 number).

## Quickstart

```bash
uv sync
uv run pytest -q                     # full suite (833 tests)
```

Reproduce the deterministic headline (free — no API calls):

```bash
uv run python packages/experiments/run_experiments.py --n 250 --seed 0
```

The paid replay backend is gated hard: it refuses to run unless
`TURNSTILE_ALLOW_PAID=1` **and** `OPENAI_API_KEY` are set, and even then requires an
explicit confirmation. Every run writes a `manifest` (git SHA, rate-table SHA-256,
seed, model ids, and which variant fields were actually applied) so any number is
reproducible and its provenance is self-describing.

## Status

The instrument is complete, reviewed, and green (833 tests, ruff clean). Waves 0–2
are done: the full pipeline, the hardened paid path (fail-loud variant guard,
reproducibility manifest, resumable checkpointing, timeout+retry, concurrency), the
kind-aware divergence gate, real-model measurement of the margin/fork-rate/preservation,
real-format ingestion, and the explorable dashboard. Current state, the paid-run
results, and the open frontier (preservation-under-divergence → open-loop; acoustic
magnitude → real audio; a live conversational agent) are tracked in
[`HANDOFF.md`](HANDOFF.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md).
