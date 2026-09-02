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
from turnstile_agent.harness import PROVENANCE, run_calls, run_leadcap_sweep
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


def _aggregate(calls, *, n: int, rates_table: RateTable) -> dict:
    """Run one set of harness calls through the built instrument
    (price -> adjudicate -> detect) and aggregate the D7 accounting. Shared
    by both 1-D sweeps (barge-in rate, buffer lead) so their numbers come
    from ONE aggregation implementation."""
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

    return {
        "n_calls": n,
        "barge_in_calls": len(barge_ins),
        "d7_findings": d7_count,
        "d7_waste_usd_total": d7_waste,
        "d7_waste_usd_mean_per_call": d7_waste / n if n else 0.0,
        "d7_waste_usd_ci95": bootstrap_ci(per_call_waste),
        "tts_spend_usd_total": tts_spend,
        "waste_share_of_tts_spend": (
            d7_waste / tts_spend if tts_spend > 0 else 0.0
        ),
        "generated_chars_total": generated_chars,
        "wasted_chars_total": wasted_chars,
        "wasted_char_share": (
            wasted_chars / generated_chars if generated_chars else 0.0
        ),
        "mean_gen_rate_realtime_x": (
            float(sum(gen_rates) / len(gen_rates)) if gen_rates else 0.0
        ),
        "mean_achieved_lead_s": (
            float(sum(leads) / len(leads)) if leads else 0.0
        ),
    }


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
    return RatePoint(barge_in_rate=rate, **_aggregate(calls, n=n, rates_table=rates_table))


class LeadCapPoint(TypedDict):
    """One point of the buffer-lead policy sweep: the barge-in rate is HELD
    at the cited default; only ``lead_cap_s`` varies."""

    lead_cap_s: float
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
    mean_gen_rate_realtime_x: float
    mean_achieved_lead_s: float


# Stated plausible POLICY BAND for a streaming TTS's buffer lead (seconds of
# generated-but-unheard audio a pipeline allows). NOT a claim about any
# vendor's pipeline -- no clean citation exists, so the band is stated and
# swept rather than asserting a single figure. It is centered plausibly
# around common 1-3s streaming-buffer designs, not around flattering any
# particular point; the corpus's cited default anchors the rate dimension,
# not this one.
LEAD_CAP_VALUES: list[float] = [0.5, 1.0, 2.0, 3.0, 4.0]

# The buffer-lead sweep holds the barge-in rate at the CITED default
# (turnstile_corpus.distributions.BARGE_IN_RATE) so the two sweeps vary one
# named parameter each.
LEAD_CAP_SWEEP_RATE = 0.15


def _run_leadcap(
    engine: TtsEngine,
    *,
    n: int,
    seed: int,
    lead_caps: list[float],
    rates_table: RateTable,
    rate: float = LEAD_CAP_SWEEP_RATE,
) -> list[LeadCapPoint]:
    """One sampling pass (barge-in draws fixed), replayed at every lead-cap
    value -- the measured phase-1 schedules are shared across points, so the
    sweep can only move the POLICY, never the measurement."""
    sweep = run_leadcap_sweep(
        engine, n=n, rate=rate, seed=seed, lead_caps=lead_caps
    )
    return [
        LeadCapPoint(
            lead_cap_s=cap,
            **_aggregate(sweep[cap], n=n, rates_table=rates_table),
        )
        for cap in lead_caps
    ]


def run_bargein_report(
    engine: TtsEngine | None = None,
    *,
    rates_values: list[float] | None = None,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    lead_cap_s: float = 2.0,
    lead_caps: list[float] | None = None,
    rates_table: RateTable | None = None,
) -> dict:
    """Run BOTH 1-D sweeps and package the measured D7 number with its
    provenance:

    * the barge-in RATE sweep (modeled input; buffer held at ``lead_cap_s``),
    * the buffer-LEAD sweep (stated policy band; rate held at the cited 0.15).

    Every call goes through the built instrument unchanged. ``engine``
    defaults to the real :class:`PiperEngine` (requires the piper extra + a
    voice model); tests inject the deterministic fake engine."""
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

    leadcap_points = _run_leadcap(
        engine, n=n, seed=seed,
        lead_caps=lead_caps if lead_caps is not None else LEAD_CAP_VALUES,
        rates_table=rates_table,
    )

    return {
        "provenance": PROVENANCE,
        "n": n,
        "seed": seed,
        "lead_cap_s": lead_cap_s,
        "parameter": "barge-in rate (modeled input, swept)",
        "class_id": D7_CLASS_ID,
        "points": points,
        "lead_cap_sweep": {
            "parameter": (
                "streaming buffer-lead policy lead_cap_s (modeled input, "
                "swept over a stated plausible policy band -- not a claim "
                "about any vendor's pipeline)"
            ),
            "barge_in_rate_held_at": LEAD_CAP_SWEEP_RATE,
            "points": leadcap_points,
        },
    }
