"""Tests for estimate_cost (packages/experiments)."""
from __future__ import annotations

import pytest

from turnstile_schema import VariantSpec, load_rates
from turnstile_schema.enums import DecisionKind

from turnstile_experiments.cost_estimate import estimate_cost

from _experiments_builders import llm, priced, turn

RATES = load_rates("pricing/rates.yaml")


def test_estimate_prices_only_decisions_at_or_after_earliest_applicable_turn(capsys):
    # turn 0: decision_kind=route (matches the routing variant's key) -- this
    # and everything after should be counted. turn -1 doesn't exist, so this
    # single-turn trace counts exactly 1 decision for the routing variant.
    trace = priced(turn(0, llm_spans=[llm("l1", decision_kind=DecisionKind.route, model="gpt-5")]))
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})

    result = estimate_cost([trace], {"routing": variant}, rates=RATES)
    capsys.readouterr()  # printed output produced without error

    assert result["per_variant"]["routing"]["num_decisions"] == 1
    rate = RATES.llm["openai/gpt-5-nano"]
    span = trace.trace.turns[0].llm[0]
    expected = span.input_tokens / 1e6 * rate.input + span.output_tokens / 1e6 * rate.output
    assert result["per_variant"]["routing"]["estimated_usd"] == pytest.approx(expected)
    assert result["total_estimated_usd"] == pytest.approx(expected)


def test_variant_with_no_matching_decision_kind_prices_nothing():
    trace = priced(turn(0, llm_spans=[llm("l1", decision_kind=DecisionKind.compose)]))
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})  # no "compose" key
    result = estimate_cost([trace], {"routing": variant}, rates=RATES)
    assert result["per_variant"]["routing"]["num_decisions"] == 0
    assert result["per_variant"]["routing"]["estimated_usd"] == 0.0


def test_variant_without_model_routing_prices_the_whole_trace_at_original_model():
    trace = priced(
        turn(0, llm_spans=[llm("l1", decision_kind=DecisionKind.route, model="gpt-5")]),
        turn(1, llm_spans=[llm("l2", decision_kind=DecisionKind.compose, model="gpt-5-mini")]),
    )
    variant = VariantSpec(context_strategy="window:8")  # no model_routing at all
    result = estimate_cost([trace], {"ctx": variant}, rates=RATES)
    assert result["per_variant"]["ctx"]["num_decisions"] == 2

    r1, r2 = RATES.llm["openai/gpt-5"], RATES.llm["openai/gpt-5-mini"]
    s1, s2 = trace.trace.turns[0].llm[0], trace.trace.turns[1].llm[0]
    expected = (
        s1.input_tokens / 1e6 * r1.input + s1.output_tokens / 1e6 * r1.output
        + s2.input_tokens / 1e6 * r2.input + s2.output_tokens / 1e6 * r2.output
    )
    assert result["per_variant"]["ctx"]["estimated_usd"] == pytest.approx(expected)


def test_total_is_sum_of_per_variant():
    trace = priced(turn(0, llm_spans=[llm("l1", decision_kind=DecisionKind.route)]))
    variants = {
        "a": VariantSpec(model_routing={"route": "gpt-5-nano"}),
        "b": VariantSpec(model_routing={"route": "gpt-5-mini"}),
    }
    result = estimate_cost([trace], variants, rates=RATES)
    expected_total = sum(v["estimated_usd"] for v in result["per_variant"].values())
    assert result["total_estimated_usd"] == pytest.approx(expected_total)


def test_prints_per_variant_and_total(capsys):
    trace = priced(turn(0, llm_spans=[llm("l1", decision_kind=DecisionKind.route)]))
    estimate_cost([trace], {"routing": VariantSpec(model_routing={"route": "gpt-5-nano"})}, rates=RATES)
    out = capsys.readouterr().out
    assert "routing" in out
    assert "TOTAL" in out
