"""Tests for compute_baselines (packages/experiments, GAP-07)."""
from __future__ import annotations

import numpy as np
import pytest

from turnstile_experiments import compute_baselines

from _experiments_builders import llm, priced, turn


def test_groups_by_scenario_id_and_computes_real_percentiles():
    # scenario "a": 3 conversations with turn counts 1, 2, 3.
    a1 = priced(turn(0, llm_spans=[llm("l1")]), scenario_id="a", conversation_id="a1")
    a2 = priced(turn(0, llm_spans=[llm("l1")]), turn(1, llm_spans=[llm("l2")]),
                scenario_id="a", conversation_id="a2")
    a3 = priced(turn(0, llm_spans=[llm("l1")]), turn(1, llm_spans=[llm("l2")]),
                turn(2, llm_spans=[llm("l3")]), scenario_id="a", conversation_id="a3")
    # scenario "b": 1 conversation, turn count 1.
    b1 = priced(turn(0, llm_spans=[llm("l1")]), scenario_id="b", conversation_id="b1")

    baselines = compute_baselines([a1, a2, a3, b1])

    assert set(baselines.per_intent.keys()) == {"a", "b"}

    expected_p50 = float(np.percentile([1, 2, 3], 50))
    expected_p75 = float(np.percentile([1, 2, 3], 75))
    a = baselines.per_intent["a"]
    assert a.p50_turns == pytest.approx(expected_p50)
    assert a.p75_turns == pytest.approx(expected_p75)

    all_turn_costs_a = a1.turn_costs + a2.turn_costs + a3.turn_costs
    assert a.mean_cost_per_turn == pytest.approx(float(np.mean(all_turn_costs_a)))

    b = baselines.per_intent["b"]
    assert b.p50_turns == pytest.approx(1.0)
    assert b.mean_cost_per_turn == pytest.approx(float(np.mean(b1.turn_costs)))


def test_empty_corpus_yields_empty_baselines():
    baselines = compute_baselines([])
    assert baselines.per_intent == {}


def test_scenario_with_no_traces_is_absent_not_zero():
    a1 = priced(turn(0, llm_spans=[llm("l1")]), scenario_id="only_a", conversation_id="a1")
    baselines = compute_baselines([a1])
    assert "never_seen" not in baselines.per_intent
    assert list(baselines.per_intent.keys()) == ["only_a"]
