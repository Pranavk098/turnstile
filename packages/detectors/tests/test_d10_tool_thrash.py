"""Unit tests for Detector 10 -- tool thrash (PRD §6 row 10)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_detectors.d10_tool_thrash import detect_tool_thrash

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, priced, tool, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_on_second_call_with_same_tool_name_and_args_hash():
    pt = priced(
        turn(0, 0, 300, tools=[tool("tool0", start=0, name="update_address", args_hash="sha256:a")]),
        turn(1, 300, 600, tools=[tool("tool1", start=300, name="update_address", args_hash="sha256:a")]),
    )
    findings = detect_tool_thrash(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 10
    assert f.turn_index == 1 and f.span_id == "tool1"
    assert f.proposed_variant.tool_batching is True
    assert f.waste_usd == pytest.approx(pt.turn_costs[1] + 0.0)


def test_third_repeat_also_flagged():
    pt = priced(
        turn(0, 0, 300, tools=[tool("tool0", start=0, name="x", args_hash="h")]),
        turn(1, 300, 600, tools=[tool("tool1", start=300, name="x", args_hash="h")]),
        turn(2, 600, 900, tools=[tool("tool2", start=600, name="x", args_hash="h")]),
    )
    findings = detect_tool_thrash(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert {f.span_id for f in findings} == {"tool1", "tool2"}


def test_silent_when_args_hash_differs():
    pt = priced(
        turn(0, 0, 300, tools=[tool("tool0", start=0, name="update_address", args_hash="sha256:a")]),
        turn(1, 300, 600, tools=[tool("tool1", start=300, name="update_address", args_hash="sha256:b")]),
    )
    assert detect_tool_thrash(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_tool_name_differs_despite_same_args_hash():
    pt = priced(
        turn(0, 0, 300, tools=[tool("tool0", start=0, name="lookup_order", args_hash="sha256:a")]),
        turn(1, 300, 600, tools=[tool("tool1", start=300, name="update_address", args_hash="sha256:a")]),
    )
    assert detect_tool_thrash(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_10_fires_on_the_duplicate_turn_only():
    pt = price_trace(load_trace(GOLDEN / "10_tool_thrash.json"), load_rates(RATES))
    findings = detect_tool_thrash(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.turn_index == 1 and f.span_id == "tool1"
    assert f.waste_usd == pytest.approx(pt.turn_costs[1])
