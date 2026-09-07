# Turnstile

**Find the money your voice AI is burning.**

![The Turnstile dashboard: every number labeled by how much it is actually measured.](docs/hero.png)

Turnstile takes a voice-agent call, prices every step (speech-to-text, the LLM, tools, text-to-speech, telephony), works out whether the call actually got resolved, and finds ten kinds of waste. For the waste it can safely fix, it proves the saving by replaying the call on a cheaper model.

One rule runs through the whole project: **never claim a number you can't back up.**

## The number that started it

**About 4% of your text-to-speech spend is generated, billed, and never heard.**

When a caller interrupts, the TTS engine has already synthesized the rest of the reply, because it runs about 40x faster than real time. You pay for audio nobody hears. We measured it on real Piper synthesis. It is also fixable: generate in smaller chunks and the waste falls from about 4% to 2.3% to 1.2%.

## Numbers you can trust, because we label every one

Turnstile sorts every claim into three buckets and never blurs them.

### Measured: numbers we stand behind
- **~4%** barge-in waste, on real TTS.
- **0.57%** recoverable margin from routing simple turns to a cheaper model. Exact arithmetic, reproducible from every run.
- On real `gpt-5-nano` calls: a **7.8%** decision-fork rate, and **98.5%** outcome preservation on the calls where the cheaper model agreed.

### Instrumented, but not measured
The mechanism works; we don't claim the size yet. This covers the rest of the cost breakdown and the silence-tax detector on synthetic audio.

### Not yet measured, and we say so
What happens when the cheaper model makes a *different* decision. We built the tool to measure it, and on today's data it honestly returns no number. The real answer needs a live agent.

The full boundaries live in [METHOD.md](docs/METHOD.md) and [LIMITATIONS.md](docs/LIMITATIONS.md).

## See it

```bash
make demo
```

This builds the report and serves it at `localhost:8000`. Open `home.html` and walk the tour: the fleet overview, then a single call in detail, then a switch to real, ingested call data.

Want it on your own calls? The `ingest` package maps real voice-AI logs into Turnstile. See [INGEST.md](docs/INGEST.md).

## How it works

```
call  ->  price  ->  verdict  ->  detect waste  ->  replay cheaper  ->  report
```

Each stage is a small package under `packages/`. The ones that carry the weight: `replay` proves the savings, `verdict` decides whether the call resolved, `detectors` finds the ten waste classes, and `dashboard` is the report you see.

## Quickstart

```bash
uv sync
uv run pytest -q        # 833 tests, all green
```

Reproduce the headline number for free, with no API calls:

```bash
uv run python packages/experiments/run_experiments.py --n 250 --seed 0
```

Paid replay is gated hard. It spends nothing unless you set `TURNSTILE_ALLOW_PAID=1` and `OPENAI_API_KEY`, and it asks before every run.

## Status

Waves 0 through 2 are done: the full pipeline, a hardened paid path, real-model measurement, real-format ingestion, and the dashboard. 833 tests pass.

Next up: measuring preservation when the model decides differently (this needs a live agent), and pointing Turnstile at real traffic at scale. Progress is tracked in [HANDOFF.md](HANDOFF.md).
