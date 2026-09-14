"""Calibration-gate tests (load-bearing for PRD 04 §3.2).

The gate review checks first: no uncalibrated model judge may emit a score
or reach the beside-cost summary. These tests pin that from every angle --
default closed, each requirement necessary, unknown ids rejected, and the
report path pending no matter what is registered (no judge implementation
ships yet, so there is nothing to call).
"""
from __future__ import annotations

import pytest

from turnstile_quality import (
    evaluate_quality,
    judge_may_score,
    register_calibration,
)
from turnstile_quality.calibration import (
    JUDGE_DIMENSIONS,
    Calibration,
    CalibrationError,
    clear_calibrations,
)

from _quality_builders import _llm, _priced, _turn, _verdict
from turnstile_schema.enums import VerdictLabel


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    clear_calibrations()
    yield
    clear_calibrations()


def _flag_on(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")


def _flag_off(monkeypatch):
    monkeypatch.delenv("TURNSTILE_ALLOW_PAID", raising=False)


def test_gate_closed_by_default():
    for dim_id in JUDGE_DIMENSIONS:
        assert judge_may_score(dim_id) is False


def test_gate_closed_without_paid_flag_even_when_calibrated(monkeypatch):
    _flag_off(monkeypatch)
    register_calibration("faithfulness",
                         Calibration(n_labels=200, kappa=0.9, ece=0.05))
    assert judge_may_score("faithfulness") is False


@pytest.mark.parametrize("cal", [
    Calibration(n_labels=59, kappa=0.9, ece=0.05),    # one label short
    Calibration(n_labels=60, kappa=0.74, ece=0.05),   # kappa below bar
    Calibration(n_labels=60, kappa=0.75, ece=None),   # ECE unreported
    Calibration(n_labels=0, kappa=0.0, ece=None),     # nothing at all
])
def test_gate_closed_until_every_requirement_met(monkeypatch, cal):
    _flag_on(monkeypatch)
    register_calibration("faithfulness", cal)
    assert judge_may_score("faithfulness") is False


def test_gate_opens_only_at_the_bar(monkeypatch):
    _flag_on(monkeypatch)
    register_calibration("faithfulness",
                         Calibration(n_labels=60, kappa=0.75, ece=0.05))
    assert judge_may_score("faithfulness") is True
    # ... but only for the calibrated dimension.
    assert judge_may_score("answer_relevance") is False


def test_gate_closed_for_unknown_dimensions(monkeypatch):
    _flag_on(monkeypatch)
    assert judge_may_score("invented_dimension") is False
    with pytest.raises(CalibrationError):
        register_calibration("invented_dimension",
                             Calibration(n_labels=60, kappa=0.75, ece=0.05))


def test_pending_judges_cannot_be_coaxed_to_score(monkeypatch):
    """Even with the flag on and a valid calibration registered, the report
    path stays pending: no judge implementation ships, so there is nothing
    that could emit a score to reach a headline or the beside-cost line."""
    _flag_on(monkeypatch)
    for dim_id in JUDGE_DIMENSIONS:
        register_calibration(dim_id, Calibration(n_labels=60, kappa=0.9, ece=0.04))
        assert judge_may_score(dim_id) is True
    report = evaluate_quality(_priced(_turn(0, llm=[_llm("l0")])),
                              _verdict(VerdictLabel.RESOLVED))
    for dim_id in JUDGE_DIMENSIONS:
        dim = report.by_id(dim_id)
        assert dim.score is None
        assert (dim.label, dim.tier, dim.method) == (
            "pending", "not_measured", "judge_pending")
    assert report.overall.label == "pass"
    assert "faithfulness" in report.evidence[2]["pending_dimensions"]


def test_no_network_imports_in_quality_package():
    """$0 by construction: the package must not even import a network client."""
    import pathlib
    import re

    package = pathlib.Path(__file__).resolve().parents[1] / "src" / "turnstile_quality"
    banned = re.compile(r"^\s*(import|from)\s+(urllib|requests|httpx|openai|socket|http\.|aiohttp)")
    offenders = [
        f"{path.name}:{i + 1}"
        for path in sorted(package.glob("*.py"))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines())
        if banned.match(line)
    ]
    assert offenders == []
