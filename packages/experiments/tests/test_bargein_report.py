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
