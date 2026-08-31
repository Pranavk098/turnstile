"""Unit tests for Detector 5 -- reprompt loop (PRD §6 row 5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_schema.enums import DecisionKind
from turnstile_pricing import price_trace
from turnstile_detectors.d05_reprompt_loop import detect_reprompt_loop

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, llm, priced, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_on_consecutive_slot_fill_with_same_decision_chosen():
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, decision_kind=DecisionKind.slot_fill, input_tokens=600, output_tokens=16)
        ]),
        turn(1, 500, 1000, llm_spans=[
            llm("l1", start=500, decision_kind=DecisionKind.slot_fill, input_tokens=650, output_tokens=17)
        ]),
    )
    # decision_chosen defaults to "x" in the shared llm() builder for both spans -> same slot.
    findings = detect_reprompt_loop(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 5
    assert f.turn_index == 1 and f.span_id == "l1"
    assert f.waste_usd == pytest.approx(pt.turn_costs[1])


def test_silent_when_not_consecutive():
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, decision_kind=DecisionKind.slot_fill, input_tokens=600, output_tokens=16)
        ]),
        turn(1, 500, 1000, llm_spans=[
            llm("l1", start=500, decision_kind=DecisionKind.compose, input_tokens=650, output_tokens=17)
        ]),
        turn(2, 1000, 1500, llm_spans=[
            llm("l2", start=1000, decision_kind=DecisionKind.slot_fill, input_tokens=650, output_tokens=17)
        ]),
    )
    assert detect_reprompt_loop(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_decision_kind_is_compose_even_if_chosen_repeats():
    # Regression guard for the false-positive this scope narrowing exists to
    # avoid (see 11_multi_waste_a's repeated compose "handle_billing" turns).
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, decision_kind=DecisionKind.compose,
                input_tokens=800, output_tokens=20)
        ]),
        turn(1, 500, 1000, llm_spans=[
            llm("l1", start=500, decision_kind=DecisionKind.compose,
                input_tokens=1300, output_tokens=20)
        ]),
    )
    assert detect_reprompt_loop(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_05_fires_with_expected_waste():
    pt = price_trace(load_trace(GOLDEN / "05_reprompt_loop.json"), load_rates(RATES))
    findings = detect_reprompt_loop(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.turn_index == 1 and f.span_id == "l1"
    assert f.waste_usd == pytest.approx(pt.turn_costs[1])


def test_golden_fixture_11_multi_waste_a_stays_silent():
    # Guards the same compose-repeat false-positive the scope narrowing exists for,
    # against the real fixture rather than a synthetic reproduction.
    pt = price_trace(load_trace(GOLDEN / "11_multi_waste_a.json"), load_rates(RATES))
    assert detect_reprompt_loop(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []
