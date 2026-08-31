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


def test_multiple_tts_and_playback_spans_are_index_matched_not_cross_multiplied():
    # CR-01 regression: a naive nested-loop `for tts in turn.tts: for
    # playback in turn.playback` cross-multiplies findings when a turn has
    # 2 tts and 2 playback spans -- here only the FIRST pair (t0/p0) wastes
    # chars; the second pair (t1/p1) plays out fully. Index-matched pairing
    # must produce exactly one finding, for the t0/p0 pair.
    pt = priced(turn(0, 0, 4000,
        tts_spans=[tts("t0", start=0, chars=1000), tts("t1", start=1000, chars=500)],
        playback_spans=[playback("p0", start=1000, chars=250), playback("p1", start=2000, chars=500)],
    ))
    findings = detect_barge_in_waste(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.span_id == "t0"
    assert f.evidence["chars_synthesized"] == 1000
    assert f.evidence["chars_played"] == 250
    assert f.evidence["wasted_chars"] == 750


def test_chars_synthesized_zero_produces_no_finding_and_does_not_raise():
    # CR-03 regression: chars_synthesized == 0 must not divide-by-zero when
    # computing wasted_fraction -- wasted_chars = 0 - played <= 0, so the
    # `continue` guard fires before that division is ever reached.
    pt = priced(turn(0, 0, 2000,
        tts_spans=[tts("t0", start=0, chars=0)],
        playback_spans=[playback("p0", start=1000, chars=0)],
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
