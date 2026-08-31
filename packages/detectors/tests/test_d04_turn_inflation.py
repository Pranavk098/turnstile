"""Unit tests for Detector 4 -- turn inflation (PRD §6 row 4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from turnstile_schema import Baselines, IntentBaseline, PricedTrace, Trace, load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_detectors.d04_turn_inflation import detect_turn_inflation

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, conv, llm, rates, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"
SAMPLE_BASELINES = Path(__file__).parents[3] / "fixtures" / "sample" / "baselines.json"


def _traced(n_turns: int, scenario_id: str) -> PricedTrace:
    ts = []
    cursor = 0
    for i in range(n_turns):
        start = cursor
        end = cursor + 500
        ts.append(turn(i, start, end, llm_spans=[llm(f"l{i}", start=start, input_tokens=500, output_tokens=15)]))
        cursor = end
    trace = Trace(conversation=conv(), turns=ts)
    trace.conversation.scenario_id = scenario_id
    return price_trace(trace, rates())


def test_fires_when_turns_exceed_p75():
    baselines = Baselines(per_intent={"order_status": IntentBaseline(
        p50_turns=8.0, p75_turns=10.0, mean_cost_per_turn=0.0012)})
    pt = _traced(14, "order_status")
    findings = detect_turn_inflation(pt, DUMMY_VERDICT, baselines)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 4
    assert f.turn_index == 13  # last turn
    assert f.proposed_variant.context_strategy == "summarize:2000"
    assert f.waste_usd == pytest.approx((14 - 8.0) * 0.0012)


def test_silent_when_turns_at_or_below_p75():
    baselines = Baselines(per_intent={"order_status": IntentBaseline(
        p50_turns=8.0, p75_turns=10.0, mean_cost_per_turn=0.0012)})
    pt = _traced(10, "order_status")
    assert detect_turn_inflation(pt, DUMMY_VERDICT, baselines) == []


def test_silent_when_scenario_has_no_baseline():
    pt = _traced(40, "some_unknown_scenario")
    assert detect_turn_inflation(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixtures_04_and_13_fire_against_sample_baselines():
    baselines = Baselines.model_validate(json.loads(SAMPLE_BASELINES.read_text(encoding="utf-8")))
    rate_table = load_rates(RATES)
    for fid, last_span in (("04_turn_inflation", "l13"), ("13_multi_waste_c", "l13")):
        pt = price_trace(load_trace(GOLDEN / f"{fid}.json"), rate_table)
        findings = detect_turn_inflation(pt, DUMMY_VERDICT, baselines)
        assert len(findings) == 1, fid
        assert findings[0].turn_index == 13
        assert findings[0].span_id == last_span


def test_golden_baseline_00_stays_silent_against_sample_baselines():
    baselines = Baselines.model_validate(json.loads(SAMPLE_BASELINES.read_text(encoding="utf-8")))
    pt = price_trace(load_trace(GOLDEN / "00_baseline_clean.json"), load_rates(RATES))
    assert detect_turn_inflation(pt, DUMMY_VERDICT, baselines) == []
