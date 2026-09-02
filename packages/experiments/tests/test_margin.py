"""Tests for recoverable_margin (packages/experiments, PRD Sec.4.3 errata)."""
from __future__ import annotations

import pytest

from turnstile_schema import ExperimentResult

from turnstile_experiments import (
    CONDITIONAL_SAVINGS_LABEL,
    RepricingResult,
    recoverable_margin,
)
from turnstile_experiments.margin import _passes_gate


def _result(n, preservation, ci95, mean=None):
    lo, hi = ci95
    return ExperimentResult(
        n=n, outcome_preservation_rate=preservation,
        delta_cost_mean=mean if mean is not None else (lo + hi) / 2.0,
        delta_cost_ci95=(lo, hi), delta_latency_p50=0.0, delta_latency_p95=0.0,
        divergent_exemplars=[],
    )


def test_gate_requires_both_preservation_and_ci_upper_negative():
    passes = _result(10, 0.95, (-0.5, -0.1))
    fails_preservation = _result(10, 0.90, (-0.5, -0.1))
    fails_ci = _result(10, 0.99, (-0.1, 0.05))
    assert _passes_gate(passes) is True
    assert _passes_gate(fails_preservation) is False
    assert _passes_gate(fails_ci) is False


def test_recoverable_margin_exact_numbers():
    # Variant A: gated. n=10, delta_cost_mean=-0.2, ci95=(-0.5, -0.1).
    a = _result(10, 1.0, (-0.5, -0.1), mean=-0.2)
    # Variant B: fails preservation gate.
    b = _result(8, 0.90, (-1.0, -0.5), mean=-0.7)
    # Variant C: fails CI gate (upper bound not negative).
    c = _result(12, 0.99, (-0.1, 0.05), mean=-0.02)

    margin = recoverable_margin({"a": a, "b": b, "c": c}, total_cost=100.0, annual_calls=1200)

    # proven_savings_usd = -mean * n = -(-0.2) * 10 = 2.0
    assert margin["proven_savings_usd"] == pytest.approx(2.0)
    # savings CI = (-hi, -lo) * n = (0.1, 0.5) * 10 = (1.0, 5.0)
    assert margin["proven_savings_usd_ci95"] == pytest.approx([1.0, 5.0])
    assert margin["total_cost_usd"] == 100.0
    assert margin["recoverable_margin_pct"] == pytest.approx(2.0)
    assert margin["recoverable_margin_pct_ci95"] == pytest.approx([1.0, 5.0])
    # n_reference = max(10, 8, 12) = 12; annualized = 2.0 * (1200/12) = 200.0
    assert margin["n_reference"] == 12
    assert margin["annualized_usd"] == pytest.approx(200.0)
    assert margin["annual_calls"] == 1200
    assert margin["gated_variants"] == ["a"]
    assert {e["variant"] for e in margin["excluded_variants"]} == {"b", "c"}


def test_never_a_bare_point_estimate():
    a = _result(10, 1.0, (-0.5, -0.1), mean=-0.2)
    margin = recoverable_margin({"a": a}, total_cost=100.0, annual_calls=1000)
    required_keys = {
        "recoverable_margin_pct", "recoverable_margin_pct_ci95",
        "total_cost_usd", "proven_savings_usd", "proven_savings_usd_ci95",
        "annualized_usd",
    }
    assert required_keys.issubset(margin.keys())
    assert isinstance(margin["recoverable_margin_pct_ci95"], list)
    assert len(margin["recoverable_margin_pct_ci95"]) == 2


def test_no_gated_variants_yields_zero_savings_not_crash():
    b = _result(8, 0.90, (-1.0, -0.5), mean=-0.7)
    margin = recoverable_margin({"b": b}, total_cost=50.0, annual_calls=1000)
    assert margin["proven_savings_usd"] == 0.0
    assert margin["recoverable_margin_pct"] == 0.0
    assert margin["gated_variants"] == []


def test_empty_matrix():
    margin = recoverable_margin({}, total_cost=0.0, annual_calls=1000)
    assert margin["proven_savings_usd"] == 0.0
    assert margin["recoverable_margin_pct"] == 0.0
    assert margin["annualized_usd"] == 0.0
    assert margin["n_reference"] == 0


# --------------------------------------------------------------------------- #
# Section A: the conditional bucket (separate from proven_savings, labeled)   #
# --------------------------------------------------------------------------- #

def test_conditional_bucket_is_separate_and_labeled():
    a = _result(10, 1.0, (-0.5, -0.1), mean=-0.2)  # gated routing variant
    cond = RepricingResult(n=10, delta_cost_mean=-0.3, delta_cost_ci95=(-0.4, -0.2))

    baseline = recoverable_margin({"a": a}, total_cost=100.0, annual_calls=1200)
    margin = recoverable_margin(
        {"a": a}, total_cost=100.0, annual_calls=1200,
        conditional={"prefix_caching_on": cond},
    )

    # The gated math is UNCHANGED by the conditional bucket's presence.
    for key in ("recoverable_margin_pct", "recoverable_margin_pct_ci95",
                "proven_savings_usd", "proven_savings_usd_ci95",
                "annualized_usd", "gated_variants", "excluded_variants"):
        assert margin[key] == baseline[key]

    bucket = margin["conditional_savings"]
    assert bucket["label"] == CONDITIONAL_SAVINGS_LABEL
    assert bucket["label"] == (
        "deterministic conditional saving — preservation unverified (Wave-2)")
    assert "H-1" in bucket["note"]
    assert "NOT in proven_savings_usd" in bucket["note"]

    v = bucket["variants"]["prefix_caching_on"]
    assert v["n"] == 10
    assert v["delta_cost_mean"] == pytest.approx(-0.3)
    assert v["savings_usd"] == pytest.approx(0.3)
    assert v["savings_usd_ci95"] == pytest.approx([0.2, 0.4])  # (-hi, -lo) flip
    assert v["label"] == CONDITIONAL_SAVINGS_LABEL
    assert bucket["total_savings_usd"] == pytest.approx(0.3)


def test_conditional_bucket_empty_by_default():
    margin = recoverable_margin({}, total_cost=10.0, annual_calls=100)
    assert margin["conditional_savings"]["variants"] == {}
    assert margin["conditional_savings"]["total_savings_usd"] == 0.0
    assert margin["conditional_savings"]["label"] == CONDITIONAL_SAVINGS_LABEL


def test_multiple_conditional_variants_sum_into_the_bucket_total():
    c1 = RepricingResult(n=5, delta_cost_mean=-0.1, delta_cost_ci95=(-0.2, -0.05))
    c2 = RepricingResult(n=5, delta_cost_mean=-0.3, delta_cost_ci95=(-0.4, -0.2))
    margin = recoverable_margin(
        {}, total_cost=10.0, annual_calls=100,
        conditional={"prefix_caching_on": c1, "other": c2},
    )
    bucket = margin["conditional_savings"]
    assert set(bucket["variants"]) == {"prefix_caching_on", "other"}
    assert bucket["total_savings_usd"] == pytest.approx(0.4)
    # and the gated side stays zero -- conditional never leaks in
    assert margin["proven_savings_usd"] == 0.0
    assert margin["gated_variants"] == []
