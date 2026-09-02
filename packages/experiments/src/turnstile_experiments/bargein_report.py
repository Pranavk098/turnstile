"""The measured barge-in number: run the native harness's calls through the
BUILT instrument (``price_trace`` -> ``adjudicate`` -> ``detect``), unchanged,
and report D7's dollar waste and share of TTS spend -- with a bootstrap CI and
a sweep over the modeled barge-in rate.

Provenance (non-negotiable, brief glm-barge-in-measured-number.md): the
reported dict embeds :data:`turnstile_agent.harness.PROVENANCE` verbatim --
real Piper TTS generation-ahead behavior, measured; barge-in rate and
position modeled and swept; N controlled harness calls, NOT production
traffic. The novel, real quantity is how much a streaming TTS bills for
audio the caller never hears; the interruption timing is the modeled input.

Baselines: ``detect()``'s D7 ignores baselines entirely (its waste is
structural char accounting), so an empty per-intent table is the honest input
for this harness -- there is no corpus here to calibrate from, and none is
invented.
"""
from __future__ import annotations

from typing import TypedDict

from turnstile_agent import TtsEngine
from turnstile_agent.harness import PROVENANCE, run_calls
from turnstile_detectors import detect
from turnstile_pricing import price_trace
from turnstile_replay._rates import get_rates
from turnstile_schema import Baselines, RateTable
from turnstile_stats import bootstrap_ci
from turnstile_verdict import adjudicate

# Sweep band: the SAME cited range the corpus D7 sweep uses
# (turnstile_experiments.sweeps.D7_BARGE_IN_RATES, centered on the telli.com
# ~15% default) -- one named modeled input, never a single tuned figure.
BARGE_IN_RATES: list[float] = [0.05, 0.10, 0.15, 0.20, 0.30]
DEFAULT_N = 150
DEFAULT_SEED = 0
D7_CLASS_ID = 7

_NO_BASELINES = Baselines(per_intent={})


class RatePoint(TypedDict):
    barge_in_rate: float
    n_calls: int
    barge_in_calls: int
    d7_findings: int
    d7_waste_usd_total: float
    d7_waste_usd_mean_per_call: float
    d7_waste_usd_ci95: tuple[float, float]
    tts_spend_usd_total: float
    waste_share_of_tts_spend: float
    generated_chars_total: int
    wasted_chars_total: int
    wasted_char_share: float
    mean_gen_rate_realtime_x: float  # MEASURED Piper generation-to-realtime
    mean_achieved_lead_s: float  # measured lead at interruption (barge-ins)


def _tts_spend_usd(priced) -> float:
    return sum(
        priced.span_costs.get(tts.span_id, 0.0)
        for turn in priced.trace.turns
        for tts in turn.tts
    )


def _run_rate(
    engine: TtsEngine,
    rate: float,
    *,
    n: int,
    seed: int,
    lead_cap_s: float,
    rates_table: RateTable,
) -> RatePoint:
    calls = run_calls(engine, n=n, rate=rate, seed=seed, lead_cap_s=lead_cap_s)

    d7_waste = 0.0
    d7_count = 0
    tts_spend = 0.0
    per_call_waste: list[float] = [0.0] * n
    for i, call in enumerate(calls):
        priced = price_trace(call.trace, rates_table)
        tts_spend += _tts_spend_usd(priced)
        verdict = adjudicate(priced)
        for finding in detect(priced, verdict, _NO_BASELINES):
            if finding.class_id == D7_CLASS_ID:
                d7_count += 1
                d7_waste += finding.waste_usd
                per_call_waste[i] += finding.waste_usd

    barge_ins = [c for c in calls if c.accounting.barge_in]
    generated_chars = sum(c.accounting.generated_chars for c in calls)
    wasted_chars = sum(c.accounting.waste_chars for c in calls)
    gen_rates = [c.accounting.gen_rate_realtime_x for c in calls]
    leads = [
        c.accounting.achieved_lead_at_barge_in_s
        for c in barge_ins
        if c.accounting.achieved_lead_at_barge_in_s is not None
    ]

    return RatePoint(
        barge_in_rate=rate,
        n_calls=n,
        barge_in_calls=len(barge_ins),
        d7_findings=d7_count,
        d7_waste_usd_total=d7_waste,
        d7_waste_usd_mean_per_call=d7_waste / n if n else 0.0,
        d7_waste_usd_ci95=bootstrap_ci(per_call_waste),
        tts_spend_usd_total=tts_spend,
        waste_share_of_tts_spend=(
            d7_waste / tts_spend if tts_spend > 0 else 0.0
        ),
        generated_chars_total=generated_chars,
        wasted_chars_total=wasted_chars,
        wasted_char_share=(
            wasted_chars / generated_chars if generated_chars else 0.0
        ),
        mean_gen_rate_realtime_x=(
            float(sum(gen_rates) / len(gen_rates)) if gen_rates else 0.0
        ),
        mean_achieved_lead_s=(
            float(sum(leads) / len(leads)) if leads else 0.0
        ),
    )


def run_bargein_report(
    engine: TtsEngine | None = None,
    *,
    rates_values: list[float] | None = None,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    lead_cap_s: float = 2.0,
    rates_table: RateTable | None = None,
) -> dict:
    """Sweep the modeled barge-in rate, pipe every call through the built
    instrument, and package the measured D7 number with its provenance.
    ``engine`` defaults to the real :class:`PiperEngine` (requires the piper
    extra + a voice model); tests inject the deterministic fake engine."""
    if engine is None:
        from turnstile_agent import PiperEngine

        engine = PiperEngine()
    rates_table = rates_table if rates_table is not None else get_rates()

    points: list[RatePoint] = [
        _run_rate(
            engine, rate, n=n, seed=seed, lead_cap_s=lead_cap_s,
            rates_table=rates_table,
        )
        for rate in (rates_values if rates_values is not None else BARGE_IN_RATES)
    ]

    return {
        "provenance": PROVENANCE,
        "n": n,
        "seed": seed,
        "lead_cap_s": lead_cap_s,
        "parameter": "barge-in rate (modeled input, swept)",
        "class_id": D7_CLASS_ID,
        "points": points,
    }
