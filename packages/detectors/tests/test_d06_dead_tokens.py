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


def test_fires_on_unvoiced_compose_even_with_a_tool_call_in_the_turn():
    """R13: no tool-call exception. A compose confirming a tool call is a
    genuine caller-facing reply -- if it's never voiced, that's real dead
    tokens, same as any other compose (this is the literal PRD rule; the
    fixtures that used to share this exact shape without a tts span --
    08_silence_tax, 10_tool_thrash, 12_multi_waste_b turns 2-3 -- were fixed
    to actually voice the confirmation instead, see the next test)."""
    pt = priced(turn(0, 0, 800,
        llm_spans=[llm("l0", start=300, input_tokens=500, output_tokens=14, output_text="Updating.")],
        tools=[tool("tool0", start=0, name="update_address")],
    ))
    findings = detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    assert findings[0].turn_index == 0 and findings[0].span_id == "l0"


def test_silent_when_a_tool_call_turn_is_actually_voiced():
    pt = priced(turn(0, 0, 1800,
        llm_spans=[llm("l0", start=300, input_tokens=500, output_tokens=14, output_text="Updating.")],
        tools=[tool("tool0", start=0, name="update_address")],
        tts_spans=[tts("t0", start=800, chars=9, text="Updating.")],
    ))
    assert detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_06_fires():
    pt = price_trace(load_trace(GOLDEN / "06_dead_tokens.json"), load_rates(RATES))
    findings = detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    assert findings[0].turn_index == 0 and findings[0].span_id == "l0"
    assert findings[0].waste_usd == pytest.approx(22 / 1e6 * 2.00)


def test_golden_fixtures_08_10_confirmations_are_silent_now_voiced():
    """R13: these used to collide with the literal D6 rule because their
    caller-facing compose confirmations had no tts span. Fixed at the fixture
    layer (fixtures/golden/_author_rest.py's `# R13:` comments) by actually
    voicing them -- confirms Detector 6 is silent on the real reason now
    (matched tts), not because of a tools-emptiness exception."""
    for fid in ("08_silence_tax", "10_tool_thrash"):
        pt = price_trace(load_trace((GOLDEN / fid).with_suffix(".json")), load_rates(RATES))
        assert detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES) == [], fid


def test_golden_fixture_12_fires_only_on_the_unvoiced_internal_note_turn():
    """12_multi_waste_b turn 0 is a genuine unvoiced internal_note (D6's real
    target here); turns 2-3 are voiced tool-call confirmations (R13) and must
    not also fire."""
    pt = price_trace(load_trace(GOLDEN / "12_multi_waste_b.json"), load_rates(RATES))
    findings = detect_dead_tokens(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert {f.turn_index for f in findings} == {0}
