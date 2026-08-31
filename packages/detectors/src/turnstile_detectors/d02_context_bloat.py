"""Detector 2 -- Context bloat (PRD §6, row 2).

Detection rule (verbatim): linear fit of `input_tokens ~ turn_index` across
the conversation's `llm.decide` spans has slope > CONTEXT_BLOAT_SLOPE_THRESHOLD
tok/turn AND `cache_read_tokens / input_tokens < CONTEXT_BLOAT_CACHE_RATIO_THRESHOLD`
(aggregated over the conversation -- a high-cache-hit-rate conversation is not
bloat, it is prefix caching already doing its job).

Waste calculation (verbatim): "tokens above a windowed-context baseline x
rate_in". The windowed baseline is modeled as the input_tokens of the
conversation's earliest llm.decide turn -- the level input_tokens would sit at
under a bounded context window (context_strategy="window:8") instead of
growing unbounded turn over turn. Every turn's input_tokens above that
baseline is context the caller paid for and would not have under a windowed
strategy; waste_usd sums (input_tokens[i] - baseline) x rate_in over turns
where that excess is positive, using each turn's own model's input rate.
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.spans import LlmDecide

from turnstile_detectors._rates import get_rates, llm_key

# PRD §6 D2, verbatim thresholds.
CONTEXT_BLOAT_SLOPE_THRESHOLD_TOK_PER_TURN = 400.0
CONTEXT_BLOAT_CACHE_RATIO_THRESHOLD = 0.5
CONTEXT_BLOAT_CONFIDENCE = 0.9  # statistical (linear fit), not a structural match


def _slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of ys ~ xs."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return numerator / denominator if denominator else 0.0


def detect_context_bloat(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    points: list[tuple[int, LlmDecide]] = [
        (turn.turn_index, span)
        for turn in trace.trace.turns
        for span in turn.llm
    ]
    if len(points) < 2:
        return []

    xs = [float(turn_index) for turn_index, _ in points]
    ys = [float(span.input_tokens) for _, span in points]
    slope = _slope(xs, ys)

    total_input = sum(span.input_tokens for _, span in points)
    total_cache_read = sum(span.cache_read_tokens for _, span in points)
    cache_ratio = (total_cache_read / total_input) if total_input else 0.0

    if not (
        slope > CONTEXT_BLOAT_SLOPE_THRESHOLD_TOK_PER_TURN
        and cache_ratio < CONTEXT_BLOAT_CACHE_RATIO_THRESHOLD
    ):
        return []

    baseline_tokens = points[0][1].input_tokens
    rates = get_rates()

    total_waste = 0.0
    worst_turn_index, worst_span, worst_excess = points[0][0], points[0][1], 0.0
    for turn_index, span in points:
        excess = span.input_tokens - baseline_tokens
        if excess <= 0:
            continue
        rate = rates.llm[llm_key(span)]
        total_waste += excess / 1e6 * rate.input
        if excess > worst_excess:
            worst_turn_index, worst_span, worst_excess = turn_index, span, excess

    if total_waste <= 0:
        return []

    return [
        Finding(
            class_id=2,
            turn_index=worst_turn_index,
            span_id=worst_span.span_id,
            waste_usd=total_waste,
            confidence=CONTEXT_BLOAT_CONFIDENCE,
            proposed_variant=VariantSpec(context_strategy="window:8", prefix_caching=True),
            evidence={
                "slope_tok_per_turn": slope,
                "cache_ratio": cache_ratio,
                "baseline_input_tokens": baseline_tokens,
                "worst_turn_excess_tokens": worst_excess,
            },
        )
    ]
