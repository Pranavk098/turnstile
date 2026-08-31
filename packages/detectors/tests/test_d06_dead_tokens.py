"""Unit tests for Detector 6 -- dead tokens (PRD §6 row 6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_schema.enums import DecisionKind
from turnstile_pricing import price_trace
from turnstile_detectors.d06_dead_tokens import detect_dead_tokens

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, llm, priced, tool, tts, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_on_compose_with_no_tts_at_all():
    pt = priced(turn(0, 0, 500, llm_spans=[
        llm("l0", start=0, input_tokens=500, output_tokens=22, output_text="unheard")
    ]))
    findings = detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 6
    assert f.turn_index == 0 and f.span_id == "l0"
    assert f.proposed_variant.tts_chunking == "sentence"
    assert f.waste_usd == pytest.approx(22 / 1e6 * 2.00)  # openai/gpt-5-mini output rate


def test_partial_voicing_scales_waste_by_unvoiced_char_fraction():
    # tts.text ("Hello") is a strict prefix of output_text ("Hello world") --
    # half the composed text (by char count) was never voiced.
    pt = priced(turn(0, 0, 500,
        llm_spans=[llm("l0", start=0, input_tokens=500, output_tokens=20, output_text="Hello world")],
        tts_spans=[tts("t0", start=0, chars=5, text="Hello")],
    ))
    findings = detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    voiced_fraction = len("Hello") / len("Hello world")
    expected_tokens = 20 * (1 - voiced_fraction)
    assert findings[0].waste_usd == pytest.approx(expected_tokens / 1e6 * 2.00)


def test_silent_when_tts_text_matches_exactly():
    pt = priced(turn(0, 0, 500,
        llm_spans=[llm("l0", start=0, input_tokens=500, output_tokens=20, output_text="Hello")],
        tts_spans=[tts("t0", start=0, chars=5, text="Hello")],
    ))
    assert detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_decision_kind_is_not_compose():
    pt = priced(turn(0, 0, 500, llm_spans=[
        llm("l0", start=0, input_tokens=500, output_tokens=20,
            decision_kind=DecisionKind.route, output_text="route this")
    ]))
    assert detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_turn_has_a_tool_call():
    """08_silence_tax / 10_tool_thrash shape: compose confirmation after a
    tool call, no tts -- Detector 6 must not collide with Detectors 8/10."""
    pt = priced(turn(0, 0, 800,
        llm_spans=[llm("l0", start=300, input_tokens=500, output_tokens=14, output_text="Updating.")],
        tools=[tool("tool0", start=0, name="update_address")],
    ))
    assert detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_06_fires():
    pt = price_trace(load_trace(GOLDEN / "06_dead_tokens.json"), load_rates(RATES))
    findings = detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    assert findings[0].turn_index == 0 and findings[0].span_id == "l0"
    assert findings[0].waste_usd == pytest.approx(22 / 1e6 * 2.00)


def test_golden_fixture_08_and_10_are_silent():
    """The exact collision this detector's `tools` guard exists to prevent."""
    for fid in ("08_silence_tax", "10_tool_thrash"):
        pt = price_trace(load_trace((GOLDEN / fid).with_suffix(".json")), load_rates(RATES))
        assert detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES) == [], fid
