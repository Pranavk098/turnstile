"""Tests for recoverable_margin (packages/experiments, PRD Sec.4.3 errata)."""
from __future__ import annotations

import pytest

from turnstile_schema import ExperimentResult

from turnstile_experiments import recoverable_margin
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
