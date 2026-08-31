"""Unit tests for Detector 1 -- over-model (PRD §6 row 1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_schema.enums import DecisionKind
from turnstile_pricing import price_trace
from turnstile_detectors.d01_over_model import (
    OVER_MODEL_OUTPUT_TOKEN_THRESHOLD,
    detect_over_model,
)

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, llm, priced, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_on_frontier_model_route_decision_under_token_threshold():
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, model="gpt-5", decision_kind=DecisionKind.route,
                input_tokens=500, output_tokens=15)
        ]),
    )
    findings = detect_over_model(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 1
    assert f.turn_index == 0 and f.span_id == "l0"
    assert f.proposed_variant.model_routing == {"route": "gpt-5-nano"}
    # actual (gpt-5): 500/1e6*1.25 + 15/1e6*10.00 ; nano: 500/1e6*0.05 + 15/1e6*0.40
    expected_waste = (500 / 1e6 * 1.25 + 15 / 1e6 * 10.00) - (500 / 1e6 * 0.05 + 15 / 1e6 * 0.40)
    assert f.waste_usd == pytest.approx(expected_waste)


def test_silent_when_output_tokens_at_or_above_threshold():
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, model="gpt-5", decision_kind=DecisionKind.route,
                input_tokens=500, output_tokens=OVER_MODEL_OUTPUT_TOKEN_THRESHOLD)
        ]),
    )
    assert detect_over_model(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_model_is_not_frontier():
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, model="gpt-5-mini", decision_kind=DecisionKind.route,
                input_tokens=500, output_tokens=15)
        ]),
    )
    assert detect_over_model(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_decision_kind_is_compose():
    pt = priced(
        turn(0, 0, 500, llm_spans=[
            llm("l0", start=0, model="gpt-5", decision_kind=DecisionKind.compose,
                input_tokens=500, output_tokens=15)
        ]),
    )
    assert detect_over_model(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_slot_fill_and_escalate_check_also_qualify():
    for kind in (DecisionKind.slot_fill, DecisionKind.escalate_check):
        pt = priced(
            turn(0, 0, 500, llm_spans=[
                llm("l0", start=0, model="gpt-5", decision_kind=kind,
                    input_tokens=500, output_tokens=15)
            ]),
        )
        findings = detect_over_model(pt, DUMMY_VERDICT, EMPTY_BASELINES)
        assert len(findings) == 1
        assert findings[0].proposed_variant.model_routing == {kind.value: "gpt-5-nano"}


def test_golden_fixture_01_fires_with_expected_waste():
    pt = price_trace(load_trace(GOLDEN / "01_over_model.json"), load_rates(RATES))
    findings = detect_over_model(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.turn_index == 0 and f.span_id == "l0"
    expected_waste = (500 / 1e6 * 1.25 + 15 / 1e6 * 10.00) - (500 / 1e6 * 0.05 + 15 / 1e6 * 0.40)
    assert f.waste_usd == pytest.approx(expected_waste)
