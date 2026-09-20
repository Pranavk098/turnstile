"""Dynamic coax suite (Day-4 Part D): the report path refuses every illegitimate gate.

The gate unit tests (test_calibration.py) pin ``judge_may_score`` as pure
logic. This module drives the RUNNING report path -- ``evaluate_quality``
over a real priced trace -- through every illegitimate opening and proves
each is refused: both judge dimensions stay
``score=None / label="pending" / tier="not_measured" / method="judge_pending"``,
the overall rolls up deterministic dimensions only, and the beside-cost
one-liner carries no digit-bearing token for a judge dimension.

Illegitimate paths (day-PRD "Recursive loop — Day-4 dynamic checks"):
  1. flag off + valid calibration registered
  2. flag on + nothing registered
  3. flag on + n=59 (one label short)
  4. flag on + kappa=0.7499 (a hair below the bar)
  5. flag on + ece=None (ECE unreported)
  6. unknown id (register raises CalibrationError, query is False)
"""
from __future__ import annotations

import re

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
from turnstile_quality.dimensions import summarize_quality

from _quality_builders import _llm, _priced, _turn, _verdict
from turnstile_schema.enums import VerdictLabel

FLAG = "TURNSTILE_ALLOW_PAID"

#: The six illegitimate paths, in spec order. Each entry is
#: (case_id, description-of-the-setup).
CASE_IDS = [
    "flag-off-valid-calibration",
    "flag-on-nothing-registered",
    "flag-on-n59",
    "flag-on-kappa-0.7499",
    "flag-on-ece-none",
    "unknown-id",
]


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_calibrations()
    yield
    clear_calibrations()


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    yield
    monkeypatch.delenv(FLAG, raising=False)


def _apply_setup(case_id: str, monkeypatch) -> str:
    """Arrange one illegitimate path. Returns the refusal evidence string."""
    valid = Calibration(n_labels=200, kappa=0.9, ece=0.05)
    if case_id == "flag-off-valid-calibration":
        monkeypatch.delenv(FLAG, raising=False)
        for dim_id in JUDGE_DIMENSIONS:
            register_calibration(dim_id, valid)
        return "flag off + valid calibration registered"
    if case_id == "flag-on-nothing-registered":
        monkeypatch.setenv(FLAG, "1")
        return "flag on + nothing registered"
    if case_id == "flag-on-n59":
        monkeypatch.setenv(FLAG, "1")
        for dim_id in JUDGE_DIMENSIONS:
            register_calibration(
                dim_id, Calibration(n_labels=59, kappa=0.9, ece=0.05))
        return "flag on + n=59 (one label short)"
    if case_id == "flag-on-kappa-0.7499":
        monkeypatch.setenv(FLAG, "1")
        for dim_id in JUDGE_DIMENSIONS:
            register_calibration(
                dim_id, Calibration(n_labels=60, kappa=0.7499, ece=0.05))
        return "flag on + kappa=0.7499 (below the 0.75 bar)"
    if case_id == "flag-on-ece-none":
        monkeypatch.setenv(FLAG, "1")
        for dim_id in JUDGE_DIMENSIONS:
            register_calibration(
                dim_id, Calibration(n_labels=60, kappa=0.9, ece=None))
        return "flag on + ece=None (ECE unreported)"
    if case_id == "unknown-id":
        monkeypatch.setenv(FLAG, "1")
        with pytest.raises(CalibrationError):
            register_calibration(
                "invented_dimension",
                Calibration(n_labels=60, kappa=0.9, ece=0.05))
        assert judge_may_score("invented_dimension") is False
        return "unknown id: register raised CalibrationError, query is False"
    raise AssertionError(f"unknown coax case {case_id!r}")  # pragma: no cover


def _expected_overall_label(report) -> str:
    """The deterministic-only rollup rule, re-derived (mirrors the contract,
    not the code): pending judges never feed it."""
    measured = [d for d in report.dimensions
                if d.score is not None and d.tier == "measured"]
    assert measured, "golden-shaped trace must have measured dimensions"
    if any(d.label == "fail" for d in measured):
        return "fail"
    if any(d.label == "partial" for d in measured):
        return "partial"
    return "pass"


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_report_path_refuses_every_illegitimate_opening(monkeypatch, case_id):
    """Each coax path -> the report still renders both judges pending."""
    setup_evidence = _apply_setup(case_id, monkeypatch)

    # The gate itself refuses on every path (unknown ids included).
    for dim_id in (*JUDGE_DIMENSIONS, "invented_dimension"):
        assert judge_may_score(dim_id) is False, (case_id, dim_id)

    report = evaluate_quality(_priced(_turn(0, llm=[_llm("l0")])),
                              _verdict(VerdictLabel.RESOLVED))

    # Both judge dims are pending-as-data, never a numeral.
    for dim_id in JUDGE_DIMENSIONS:
        dim = report.by_id(dim_id)
        assert dim.score is None, (case_id, dim_id)
        assert (dim.label, dim.tier, dim.method) == (
            "pending", "not_measured", "judge_pending"), (case_id, dim_id)

    # Overall comes from the deterministic dimensions only.
    assert report.overall.label == _expected_overall_label(report), case_id
    assert report.overall.label == "pass", case_id
    assert report.overall.tier == "measured", case_id
    assert sorted(report.evidence[2]["pending_dimensions"]) == sorted(
        JUDGE_DIMENSIONS), case_id

    # The beside-cost one-liner names no judge dim and carries no
    # digit-bearing token for one: the only numeral is the $ cost.
    priced = _priced(_turn(0, llm=[_llm("l0")]))
    line = summarize_quality(report.overall.label, report.overall.tier,
                             priced.conv_cost)
    assert "faithfulness" not in line and "answer_relevance" not in line
    digit_tokens = [tok for tok in re.split(r"\s+", line) if re.search(r"\d", tok)]
    assert len(digit_tokens) == 1 and digit_tokens[0].startswith("$"), line

    # Coax-matrix transcript row (visible with `pytest -s`).
    print(f"\n[coax] {case_id}: {setup_evidence} -> "
          f"judge_may_score=False x2; report faithfulness/answer_relevance "
          f"pending/not_measured/judge_pending; overall={report.overall.label}; "
          f"beside-cost={line!r}")
