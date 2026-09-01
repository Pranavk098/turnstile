"""Unit tests for Detector 2 -- context bloat (PRD §6 row 2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_detectors.d02_context_bloat import (
    CONTEXT_BLOAT_CACHE_RATIO_THRESHOLD,
    CONTEXT_BLOAT_SLOPE_THRESHOLD_TOK_PER_TURN,
    detect_context_bloat,
)

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, llm, priced, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_when_slope_exceeds_threshold_and_cache_ratio_is_low():
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=500, output_tokens=10)]),
        turn(1, 500, 1000, llm_spans=[llm("l1", start=500, input_tokens=1000, output_tokens=10)]),
        turn(2, 1000, 1500, llm_spans=[llm("l2", start=1000, input_tokens=1500, output_tokens=10)]),
    )
    findings = detect_context_bloat(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 2
    assert f.turn_index == 2  # worst (highest-excess) turn
    assert f.span_id == "l2"
    assert f.proposed_variant.context_strategy == "window:8"
    assert f.proposed_variant.prefix_caching is True
    # baseline = turn0's 500 tokens; excess = (1000-500) + (1500-500) = 1500
    expected_waste = 1500 / 1e6 * 0.25  # openai/gpt-5-mini input rate, pricing/rates.yaml
    assert f.waste_usd == pytest.approx(expected_waste)


def test_silent_when_slope_at_or_below_threshold():
    step = CONTEXT_BLOAT_SLOPE_THRESHOLD_TOK_PER_TURN  # exactly at threshold, not >
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=500, output_tokens=10)]),
        turn(1, 500, 1000, llm_spans=[llm("l1", start=500, input_tokens=500 + step, output_tokens=10)]),
    )
    assert detect_context_bloat(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_cache_ratio_at_or_above_threshold_despite_steep_slope():
    total_input = 500 + 1500  # turn0 + turn1 input_tokens, defined below
    cache = int(CONTEXT_BLOAT_CACHE_RATIO_THRESHOLD * total_input)  # ratio == threshold, not <
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=500, output_tokens=10)]),
        turn(1, 500, 1000, llm_spans=[
            llm("l1", start=500, input_tokens=1500, output_tokens=10, cache_read_tokens=cache)
        ]),
    )
    assert detect_context_bloat(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_with_fewer_than_two_llm_spans():
    pt = priced(turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=10_000, output_tokens=10)]))
    assert detect_context_bloat(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_02_fires_with_expected_waste():
    pt = price_trace(load_trace(GOLDEN / "02_context_bloat.json"), load_rates(RATES))
    findings = detect_context_bloat(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.turn_index == 4
    assert f.span_id == "l4"
    # tokens 800,1300,1900,2600,3400; baseline=800; excess sum=500+1100+1800+2600=6000
    expected_waste = 6000 / 1e6 * 0.25
    assert f.waste_usd == pytest.approx(expected_waste)
