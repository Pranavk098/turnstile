"""Unit tests for Detector 8 -- silence tax (PRD §6 row 8; docs/GATES.md G1).

`test_heavy_overlap_still_reports_real_silence_a_sum_would_hide` is the
specific regression the task brief calls out: "a sum-of-durations instead of
a union is THE bug to avoid -- overlapping spans must count once." A
sum-based implementation systematically OVER-counts active time whenever
spans overlap (each overlapping span's duration is counted again), which
makes it UNDER-report silence relative to the true union -- so the
discriminating case needs overlap large enough that sum(durations) actually
exceeds the union, hiding real, billed dead air a correct union would catch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_detectors.d08_silence_tax import SILENCE_GAP_THRESHOLD_MS, detect_silence_tax

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, leg, llm, priced, tool, tts, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"
TEL_RATE_PER_SEC = 0.0085 / 60.0  # twilio/pstn_inbound, pricing/rates.yaml


def test_overlapping_spans_count_once_in_active_ms():
    """tool[0,300) and llm[100,700) overlap by 200ms. Correct union active_ms
    = |[0,300) ∪ [100,700)| = 700ms (not 300+600=900, which double-counts the
    [100,300) overlap). Billed wall is exactly 700ms -> zero real silence."""
    pt = priced(turn(0, 0, 700,
        tools=[tool("tool0", start=0, dur=300)],
        llm_spans=[llm("l0", start=100, dur=600, input_tokens=10, output_tokens=10)],
    ), telephony=leg())
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_heavy_overlap_still_reports_real_silence_a_sum_would_hide():
    """tool[0,600) and llm[0,600) fully overlap (identical interval). Union
    active_ms = 600ms; billed wall = 1000ms -> 400ms of real, billed silence,
    well past threshold: must fire. A sum-of-durations implementation would
    compute "active" = 600+600 = 1200ms > the 1000ms wall, conclude zero (or
    negative, clamped) silence, and wrongly stay silent -- exactly the bug
    PRD §6 D8 calls out by name ("union, not sum")."""
    pt = priced(turn(0, 0, 1000,
        tools=[tool("tool0", start=0, dur=600)],
        llm_spans=[llm("l0", start=0, dur=600, input_tokens=10, output_tokens=10)],
    ), telephony=leg())
    findings = detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    assert findings[0].evidence["silence_ms"] == 400
    assert findings[0].waste_usd == pytest.approx(400 / 1000.0 * TEL_RATE_PER_SEC)


def test_fires_on_trailing_gap_past_threshold():
    pt = priced(turn(0, 0, 6000,
        tools=[tool("tool0", start=0, dur=300)],
        llm_spans=[llm("l0", start=300, dur=500, input_tokens=10, output_tokens=10)],
    ), telephony=leg(billable_seconds=6))
    findings = detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 8
    assert f.turn_index == 0 and f.span_id == "l0"
    assert f.evidence["silence_ms"] == 6000 - 800
    assert f.evidence["trailing_gap"] is True
    assert f.evidence["attributed_to"] == "tts_ttfb"  # last active was llm -> next was TTS
    assert f.proposed_variant.model_routing == {"compose": "gpt-5-nano"}
    assert f.waste_usd == pytest.approx((6000 - 800) / 1000.0 * TEL_RATE_PER_SEC)


def test_silent_when_gap_is_within_jitter_threshold():
    pt = priced(turn(0, 0, 800 + SILENCE_GAP_THRESHOLD_MS,
        llm_spans=[llm("l0", start=0, dur=800, input_tokens=10, output_tokens=10)],
    ), telephony=leg())
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_mid_turn_gap_attributed_to_the_literal_next_span():
    """asr ends at 300; llm doesn't start until 900 -- 600ms mid-turn gap
    attributed directly to "model" (the llm span that starts next), per the
    literal PRD wording, not the trailing-gap fallback table."""
    pt = priced(turn(0, 0, 1400,
        tools=[tool("tool0", start=0, dur=300)],
        llm_spans=[llm("l0", start=900, dur=500, input_tokens=10, output_tokens=10)],
    ), telephony=leg())
    findings = detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    assert findings[0].evidence["attributed_to"] == "model"
    assert findings[0].evidence["trailing_gap"] is False
    assert findings[0].proposed_variant.tool_batching is None  # model, not tool_batching


def test_silent_without_a_telephony_leg():
    pt = priced(turn(0, 0, 10_000, llm_spans=[llm("l0", start=0, dur=100, input_tokens=10, output_tokens=10)]))
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_08_fires_with_expected_waste_and_attribution():
    pt = price_trace(load_trace(GOLDEN / "08_silence_tax.json"), load_rates(RATES))
    findings = detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.evidence["silence_ms"] == 5200
    assert f.evidence["attributed_to"] == "tts_ttfb"
    assert f.waste_usd == pytest.approx(5200 / 1000.0 * TEL_RATE_PER_SEC)


def test_golden_fixture_19_edge_40_turn_is_silent_despite_cross_turn_overlap():
    """manifest.yaml: turn 6's llm.decide overlaps turn 5's audio.playback --
    the fixture exists specifically to probe the union computation across a
    turn boundary. target_detector is none: D8 must stay silent."""
    pt = price_trace(load_trace(GOLDEN / "19_edge_40_turn.json"), load_rates(RATES))
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []
