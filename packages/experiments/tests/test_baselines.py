"""Tests for compute_baselines (packages/experiments, GAP-07)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_schema import load_rates

from turnstile_experiments import compute_baselines

from _experiments_builders import llm, priced, turn

ROOT = Path("pricing").resolve().parent  # repo root (tests run from there)
BASELINES_PATH = ROOT / "fixtures" / "sample" / "baselines.json"
PROVENANCE_PATH = ROOT / "fixtures" / "sample" / "baselines.provenance.json"


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


# --------------------------------------------------------------------------- #
# B1 (GAP-07): fixtures/sample/baselines.json is corpus-calibrated, with the   #
# stated n/seed recorded in its provenance file -- no magic numbers.           #
# --------------------------------------------------------------------------- #

def test_sample_baselines_equal_corpus_percentiles_for_the_stated_n_seed():
    """The acceptance test: the checked-in baselines.json's p50/p75 (and mean
    per-turn cost) are EXACTLY compute_baselines over generate_corpus at the
    n/seed its provenance file states -- not hand-authored constants."""
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    n, seed = provenance["n"], provenance["seed"]

    rates = load_rates(ROOT / "pricing" / "rates.yaml")
    corpus = [price_trace(t, rates) for t in generate_corpus(n, seed)]
    computed = compute_baselines(corpus)

    checked_in = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))["per_intent"]
    assert set(checked_in) == set(computed.per_intent)
    for sid, v in computed.per_intent.items():
        row = checked_in[sid]
        assert row["p50_turns"] == pytest.approx(v.p50_turns), sid
        assert row["p75_turns"] == pytest.approx(v.p75_turns), sid
        assert row["mean_cost_per_turn"] == pytest.approx(v.mean_cost_per_turn), sid


def test_sample_baselines_provenance_records_the_selection():
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    for key in ("n", "seed", "generated_utc", "calibration", "per_intent_sample_counts"):
        assert key in provenance, key
    # Canonical parameters (n=250, seed=0 -- no seed selection), and the
    # fixture-09/D4 reconciliation, must be stated, not hidden.
    assert provenance["seed"] == 0
    assert "fixture 09" in provenance["selection_note"]
    assert "4,9" in provenance["selection_note"] or "D4" in provenance["selection_note"]
    # Every calibrated scenario traces to actual corpus samples.
    counts = provenance["per_intent_sample_counts"]
    baselines = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))["per_intent"]
    assert set(counts) == set(baselines)
    assert all(c > 0 for c in counts.values())
