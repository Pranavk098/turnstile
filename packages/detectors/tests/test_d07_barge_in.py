"""Unit tests for Detector 7 -- barge-in waste (PRD §6 row 7)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_detectors.d07_barge_in import detect_barge_in_waste

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, llm, playback, priced, tts, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_when_synthesized_exceeds_played():
    pt = priced(turn(0, 0, 2000,
        llm_spans=[llm("l0", start=0, input_tokens=100, output_tokens=100, model="gpt-5")],
        tts_spans=[tts("t0", start=0, chars=1000)],
        playback_spans=[playback("p0", start=1000, chars=250)],
    ))
    findings = detect_barge_in_waste(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 7
    assert f.turn_index == 0 and f.span_id == "t0"
    assert f.proposed_variant.tts_chunking == "sentence"

    wasted_fraction = 750 / 1000
    tts_cost = 1000 / 1000 * 0.025  # piper rate
    expected_tts_waste = tts_cost * wasted_fraction
    expected_llm_waste = (100 * wasted_fraction) / 1e6 * 10.00  # openai/gpt-5 output rate
    assert f.waste_usd == pytest.approx(expected_tts_waste + expected_llm_waste)
    assert f.evidence["wasted_chars"] == 750


def test_silent_when_played_covers_all_synthesized_chars():
    pt = priced(turn(0, 0, 2000,
        tts_spans=[tts("t0", start=0, chars=500)],
        playback_spans=[playback("p0", start=1000, chars=500)],
    ))
    assert detect_barge_in_waste(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_played_exceeds_synthesized():
    # Should not happen in practice, but the rule is a strict ">", not "!=".
    pt = priced(turn(0, 0, 2000,
        tts_spans=[tts("t0", start=0, chars=500)],
        playback_spans=[playback("p0", start=1000, chars=600)],
    ))
    assert detect_barge_in_waste(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_07_fires_with_expected_waste():
    pt = price_trace(load_trace(GOLDEN / "07_barge_in_waste.json"), load_rates(RATES))
    findings = detect_barge_in_waste(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.turn_index == 0 and f.span_id == "t0"
    assert f.evidence["chars_synthesized"] == 184
    assert f.evidence["chars_played"] == 61
    wasted_fraction = (184 - 61) / 184
    tts_cost = 184 / 1000 * 0.025
    expected_tts_waste = tts_cost * wasted_fraction
    expected_llm_waste = (140 * wasted_fraction) / 1e6 * 10.00
    assert f.waste_usd == pytest.approx(expected_tts_waste + expected_llm_waste)
