"""Tests for the stats package (packages/stats).

The oracle for this module: known reference values for the Wilson interval, a
deterministic bootstrap, and a hand-built list of Trials that must collapse to
one exact ExperimentResult.

Note on the brief's Wilson reference: ``wilson_interval(96,100)`` per the given
formula yields (0.9016, 0.9843), not (0.9007, 0.9840). The brief's own 50/100
reference (0.4038, 0.5962) matches the formula exactly, so the 96/100 line in
the brief is treated as a typo; the formula is authoritative ("do not
approximate a formula").
"""
from __future__ import annotations

import numpy as np
import pytest

from turnstile_schema import Trial
from turnstile_stats import aggregate_experiment, bootstrap_ci, wilson_interval

# --------------------------------------------------------------------------- #
# wilson_interval                                                              #
# --------------------------------------------------------------------------- #

def test_wilson_reference_96_of_100():
    lo, hi = wilson_interval(96, 100)
    assert lo == pytest.approx(0.9016, abs=1e-3)
    assert hi == pytest.approx(0.9843, abs=1e-3)


def test_wilson_reference_50_of_100():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3)
    assert hi == pytest.approx(0.5962, abs=1e-3)


def test_wilson_zero_n_is_zero_interval():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_monotonic_in_successes():
    centers = [sum(wilson_interval(k, 100)) / 2 for k in (40, 50, 60, 70)]
    assert all(b > a for a, b in zip(centers, centers[1:]))


def test_wilson_clamped_to_unit_interval():
    lo0, hi0 = wilson_interval(0, 100)
    lo100, hi100 = wilson_interval(100, 100)
    assert lo0 >= 0.0 and hi0 <= 1.0 and lo0 <= hi0
    assert lo100 >= 0.0 and hi100 <= 1.0 and lo100 <= hi100
    assert lo100 > lo0


# --------------------------------------------------------------------------- #
# bootstrap_ci                                                                 #
# --------------------------------------------------------------------------- #

VALUES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def test_bootstrap_deterministic_with_default_seed():
    assert bootstrap_ci(VALUES) == bootstrap_ci(VALUES)


def test_bootstrap_seed_changes_the_interval():
    assert bootstrap_ci(VALUES, seed=1) != bootstrap_ci(VALUES, seed=999)


def test_bootstrap_brackets_sample_mean():
    values = np.random.default_rng(0).normal(1.0, 0.1, 200).tolist()
    lo, hi = bootstrap_ci(values)
    mean = float(np.mean(values))
    assert lo <= mean <= hi


def test_bootstrap_normal_sample_ci_is_small_and_symmetric():
    values = np.random.default_rng(0).normal(1.0, 0.1, 200).tolist()
    lo, hi = bootstrap_ci(values)
    half = (hi - lo) / 2
    assert half < 0.05
    assert abs((lo + hi) / 2 - float(np.mean(values))) < 0.02


def test_bootstrap_empty_is_zero():
    assert bootstrap_ci([]) == (0.0, 0.0)


def test_bootstrap_single_value_is_point_estimate():
    assert bootstrap_ci([2.5]) == (2.5, 2.5)


def test_bootstrap_99_ci_wider_than_95():
    values = np.random.default_rng(0).normal(1.0, 0.1, 200).tolist()
    lo95, hi95 = bootstrap_ci(values, ci=0.95)
    lo99, hi99 = bootstrap_ci(values, ci=0.99)
    assert (hi99 - lo99) > (hi95 - lo95)


# --------------------------------------------------------------------------- #
# aggregate_experiment                                                         #
# --------------------------------------------------------------------------- #

def _trial(trace_id, status="ok", delta_cost=None, delta_latency_ms=None,
           outcome_preserved=None) -> Trial:
    return Trial(
        trace_id=trace_id, status=status, delta_cost=delta_cost,
        delta_latency_ms=delta_latency_ms, outcome_preserved=outcome_preserved,
    )


def test_aggregate_excluded_trials_do_not_count_toward_n():
    trials = [
        _trial("a", outcome_preserved=True, delta_cost=-0.01, delta_latency_ms=-100.0),
        _trial("b", outcome_preserved=False, delta_cost=0.02, delta_latency_ms=50.0),
        _trial("c", status="excluded", outcome_preserved=True,
               delta_cost=-0.99, delta_latency_ms=-999.0),
    ]
    res = aggregate_experiment(trials)
    assert res.n == 2
    assert res.outcome_preservation_rate == pytest.approx(0.5)


def test_aggregate_divergent_goes_to_exemplars_and_is_excluded_from_delta():
    trials = [
        _trial("a", outcome_preserved=True, delta_cost=-0.01, delta_latency_ms=-100.0),
        _trial("d1", status="divergent", delta_cost=5.0, delta_latency_ms=900.0),
        _trial("d2", status="divergent", delta_cost=7.0, delta_latency_ms=1200.0),
    ]
    res = aggregate_experiment(trials)
    assert res.n == 3
    assert res.divergent_exemplars == ["d1", "d2"]
    assert res.delta_cost_mean == pytest.approx(-0.01)      # divergent deltas dropped
    assert res.delta_latency_p50 == pytest.approx(-100.0)   # divergent latencies dropped


def test_aggregate_known_latency_percentiles():
    trials = [
        _trial(f"t{i}", outcome_preserved=True, delta_cost=0.0,
               delta_latency_ms=float(i))
        for i in range(21)
    ]
    res = aggregate_experiment(trials)
    assert res.n == 21
    assert res.outcome_preservation_rate == pytest.approx(1.0)
    assert res.delta_cost_mean == pytest.approx(0.0)
    assert res.delta_latency_p50 == pytest.approx(10.0)
    assert res.delta_latency_p95 == pytest.approx(19.0)
    assert res.divergent_exemplars == []


def test_aggregate_hand_built_list_produces_expected_result():
    trials = [
        _trial("a", outcome_preserved=True, delta_cost=-0.01, delta_latency_ms=-100.0),
        _trial("b", outcome_preserved=True, delta_cost=-0.02, delta_latency_ms=-50.0),
        _trial("c", outcome_preserved=False, delta_cost=0.0, delta_latency_ms=0.0),
        _trial("d", status="divergent", delta_cost=0.5, delta_latency_ms=200.0),
        _trial("e", status="excluded", outcome_preserved=False,
               delta_cost=-0.5, delta_latency_ms=-900.0),
    ]
    res = aggregate_experiment(trials)
    assert res.n == 4
    assert res.outcome_preservation_rate == pytest.approx(2 / 3)
    assert res.delta_cost_mean == pytest.approx(-0.01)
    assert res.delta_cost_ci95 == pytest.approx(bootstrap_ci([-0.01, -0.02, 0.0]))
    assert res.delta_cost_ci95[0] <= res.delta_cost_mean <= res.delta_cost_ci95[1]
    assert res.delta_latency_p50 == pytest.approx(-50.0)
    assert res.delta_latency_p95 == pytest.approx(-5.0)
    assert res.divergent_exemplars == ["d"]


def test_aggregate_wilson_interval_from_same_counts():
    trials = [
        _trial("a", outcome_preserved=True, delta_cost=0.0, delta_latency_ms=0.0),
        _trial("b", outcome_preserved=True, delta_cost=0.0, delta_latency_ms=0.0),
        _trial("c", outcome_preserved=False, delta_cost=0.0, delta_latency_ms=0.0),
    ]
    res = aggregate_experiment(trials)
    successes = sum(
        1 for t in trials
        if t.status != "excluded" and t.outcome_preserved is not None and t.outcome_preserved
    )
    count = sum(
        1 for t in trials
        if t.status != "excluded" and t.outcome_preserved is not None
    )
    ci = wilson_interval(successes, count)
    assert res.outcome_preservation_rate == pytest.approx(successes / count)
    assert ci[0] <= res.outcome_preservation_rate <= ci[1]


def test_aggregate_empty_trial_list_constructs():
    res = aggregate_experiment([])
    assert res.n == 0
    assert res.outcome_preservation_rate == 0.0
    assert res.delta_cost_mean == 0.0
    assert res.delta_cost_ci95 == (0.0, 0.0)
    assert res.delta_latency_p50 == 0.0
    assert res.delta_latency_p95 == 0.0
    assert res.divergent_exemplars == []