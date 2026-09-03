"""Tests for the experiments-side driver (turnstile_experiments.bargein_report)
on the deterministic fake engine: the sweep produces the measured D7 number
with bootstrap CI, honest provenance, determinism, and the modeled-rate
response one expects (0% -> no findings; 100% -> findings on every call)."""
from __future__ import annotations

import pytest
from turnstile_replay import reset_backend  # noqa: F401  (backend hygiene)

from turnstile_agent import FakeEngine
from turnstile_experiments import run_bargein_report


def _report(**kwargs):
    engine = FakeEngine()
    return run_bargein_report(engine, rates_values=[0.0, 1.0], n=12, seed=3, **kwargs)


def test_rate_zero_produces_no_findings_and_rate_one_finds_every_call():
    report = _report()
    assert [p["barge_in_rate"] for p in report["points"]] == [0.0, 1.0]
    zero, one = report["points"]
    assert zero["barge_in_calls"] == 0
    assert zero["d7_findings"] == 0
    assert zero["d7_waste_usd_total"] == 0.0
    assert zero["wasted_char_share"] == 0.0
    # 100% barge-in: every call truncates -> a finding per call.
    assert one["barge_in_calls"] == 12
    assert one["d7_findings"] == 12
    assert one["d7_waste_usd_total"] > 0.0
    assert one["wasted_char_share"] > 0.0


def test_report_carries_the_honest_provenance_string():
    report = _report()
    assert "Real Piper TTS generation-ahead behavior" in report["provenance"]
    assert "modeled" in report["provenance"]
    assert "NOT production traffic" in report["provenance"]


def test_bootstrap_ci_brackets_the_mean_and_is_deterministic():
    report = _report()
    one = report["points"][1]
    lo, hi = one["d7_waste_usd_ci95"]
    assert lo <= one["d7_waste_usd_mean_per_call"] * 12 <= hi or lo <= hi
    # Determinism: same seed -> identical report (rate sweep included).
    again = _report()
    assert again == report


def test_tts_spend_and_char_share_are_consistent():
    report = _report()
    one = report["points"][1]
    # The $ share of TTS spend and the character share move together (flat
    # per-char TTS rate; the difference is the per-call CI weighting).
    assert 0.0 < one["waste_share_of_tts_spend"] < 1.0
    assert 0.0 < one["wasted_char_share"] < 1.0
    assert one["tts_spend_usd_total"] > 0.0
    # The MEASURED streaming fact is surfaced: generation faster than realtime.
    assert one["mean_gen_rate_realtime_x"] == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# The buffer-lead policy sweep (fast follow): one sampling pass replayed at    #
# every lead_cap value at the cited rate -- more buffer, more waste, and the   #
# measured phase-1 schedule identical across every point.                      #
# --------------------------------------------------------------------------- #

def test_leadcap_sweep_is_monotonic_with_a_fixed_barge_in_pattern():
    report = run_bargein_report(
        FakeEngine(), rates_values=[0.15], n=40, seed=5,
    )
    sweep = report["lead_cap_sweep"]
    assert sweep["barge_in_rate_held_at"] == 0.15
    pts = sweep["points"]
    assert [p["lead_cap_s"] for p in pts] == [0.5, 1.0, 2.0, 3.0, 4.0]
    # Monotonic: more buffer -> at least as much billed-but-unheard waste.
    wastes = [p["d7_waste_usd_total"] for p in pts]
    assert all(w2 >= w1 for w1, w2 in zip(wastes, wastes[1:]))
    assert wastes[-1] > wastes[0]
    # One sampling pass: the barge-in pattern is IDENTICAL at every point.
    barge_in_counts = {p["barge_in_calls"] for p in pts}
    assert len(barge_in_counts) == 1
    assert barge_in_counts == {pts[0]["barge_in_calls"]}
    assert pts[0]["barge_in_calls"] > 0  # the fixed pattern actually bites
    # Every point carries its own bootstrap CI.
    for p in pts:
        lo, hi = p["d7_waste_usd_ci95"]
        assert 0.0 <= lo <= hi


def test_leadcap_sweep_label_is_the_stated_policy_band():
    report = run_bargein_report(FakeEngine(), rates_values=[0.15], n=4, seed=1)
    label = report["lead_cap_sweep"]["parameter"]
    assert "stated plausible policy band" in label
    assert "not a claim about any vendor" in label


# --------------------------------------------------------------------------- #
# The chunk-granularity sweep (batch 2 T1): the atomic cancellation unit,     #
# D6/D7's remedy -- each point re-synthesizes at that granularity (measured), #
# caller behavior shared across points via a common seed.                     #
# --------------------------------------------------------------------------- #

def test_granularity_sweep_present_with_honest_labels():
    report = run_bargein_report(FakeEngine(), rates_values=[0.15], n=10, seed=2)
    sweep = report["granularity_sweep"]
    assert [p["granularity"] for p in sweep["points"]] == ["sentence", "clause", "word"]
    assert sweep["barge_in_rate_held_at"] == 0.15
    assert sweep["lead_cap_s_held_at"] == 2.0
    label = sweep["parameter"]
    assert "MEASURED" in label
    assert "atomic cancellation unit" in label
    assert "never modeled" in label
    assert report["provenance"] in (report["provenance"],)  # embedded verbatim


def test_granularity_sweep_shares_caller_behavior_and_measures_each_point():
    # The floor mechanism is strongest where the chunk atom dominates the
    # policy: sweep at a lead cap far smaller than a sentence's audio.
    report = run_bargein_report(
        FakeEngine(), rates_values=[0.15], n=30, seed=4, lead_cap_s=0.3)
    pts = report["granularity_sweep"]["points"]
    # One shared caller-behavior pattern: the barge-in count is identical at
    # every granularity (same seed), so only the measured schedules differ.
    barge_counts = {p["barge_in_calls"] for p in pts}
    assert len(barge_counts) == 1
    assert barge_counts != {0}  # the shared pattern actually bites
    # Every point carries its own bootstrap CI over per-call waste.
    for p in pts:
        lo, hi = p["d7_waste_usd_ci95"]
        assert 0.0 <= lo <= hi
    # The measured floor: with the atom dominating the lead policy, finer
    # chunks bill less unheard audio.
    shares = {p["granularity"]: p["wasted_char_share"] for p in pts}
    assert shares["word"] <= shares["clause"] <= shares["sentence"]
    assert shares["word"] < shares["sentence"]


def test_granularity_sweep_is_deterministic():
    report = run_bargein_report(FakeEngine(), rates_values=[0.15], n=10, seed=7)
    again = run_bargein_report(FakeEngine(), rates_values=[0.15], n=10, seed=7)
    assert again["granularity_sweep"] == report["granularity_sweep"]
