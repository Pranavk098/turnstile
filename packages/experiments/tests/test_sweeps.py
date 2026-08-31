"""Tests for the D7/D8 sensitivity sweeps (packages/experiments/sweeps.py +
turnstile_experiments.sweeps): they must run the full pipeline, vary only the
one named parameter per sweep, and produce non-degenerate, monotonic-ish
curves (docs/DEMO.md "Detector 8 as a hypothesis, not a claim").
"""
from __future__ import annotations

from turnstile_corpus import distributions as corpus_dist
from turnstile_schema import load_rates

from turnstile_experiments.sweeps import run_d7_barge_in_sweep, run_d8_silence_sweep, run_sweeps

RATES = load_rates("pricing/rates.yaml")

# Small n and few points for test speed; the shipped CLI default is larger
# (see turnstile_experiments.sweeps.DEFAULT_N) and documented in
# sweeps-report.md.
N = 25
SEED = 7


def test_d7_sweep_is_monotonic_and_varies_only_barge_in_rate():
    original = corpus_dist.BARGE_IN_RATE
    points = run_d7_barge_in_sweep(RATES, n=N, seed=SEED, values=[0.05, 0.15, 0.40])

    assert [p["param_value"] for p in points] == [0.05, 0.15, 0.40]
    # More barge-in -> more D7 findings and more D7 waste (non-degenerate,
    # monotonic across a 8x spread in the rate).
    findings = [p["detector_findings"] for p in points]
    waste = [p["detector_waste_usd"] for p in points]
    assert findings == sorted(findings)
    assert waste == sorted(waste)
    assert findings[0] < findings[-1]
    assert waste[0] < waste[-1]
    for p in points:
        assert p["total_findings"] >= p["detector_findings"]
        assert 0.0 <= p["detector_share_of_findings"] <= 1.0
    # The named module-level constant is untouched by the sweep.
    assert corpus_dist.BARGE_IN_RATE == original


def test_d8_sweep_is_monotonic_and_restores_the_constant():
    original = corpus_dist.INTER_TURN_GAP_MEDIAN_MS
    points = run_d8_silence_sweep(RATES, n=N, seed=SEED, values=[100.0, 200.0, 450.0])

    assert [p["param_value"] for p in points] == [100.0, 200.0, 450.0]
    # Wider silence gaps -> more D8 waste and a larger share of all findings
    # (docs/DEMO.md: D8's share moves with this parameter, not a bare 82%).
    waste = [p["detector_waste_usd"] for p in points]
    share = [p["detector_share_of_findings"] for p in points]
    assert waste == sorted(waste)
    assert share == sorted(share)
    assert waste[0] < waste[-1]
    assert share[0] < share[-1]
    for p in points:
        assert p["detector_findings"] > 0
        assert p["total_findings"] >= p["detector_findings"]
    # The monkeypatch used to thread the override through must not leak.
    assert corpus_dist.INTER_TURN_GAP_MEDIAN_MS == original


def test_run_sweeps_shape():
    results = run_sweeps(RATES, n=N, seed=SEED)

    assert results["n"] == N
    assert results["seed"] == SEED
    for key, class_id in (("d7_barge_in_sweep", 7), ("d8_silence_sweep", 8)):
        assert results[key]["class_id"] == class_id
        assert len(results[key]["points"]) >= 3
        for point in results[key]["points"]:
            assert set(point) == {
                "param_value", "detector_findings", "detector_waste_usd",
                "total_findings", "detector_share_of_findings",
            }
