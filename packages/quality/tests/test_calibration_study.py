"""Tests for calibration_study (Day-4 Part B).

Known-answer vectors: perfect agreement -> 1.0; McHugh (2012) worked example;
chance-level -> 0. Perfect calibration -> ECE 0.0; a hand-computed 2-bin ECE.
Plus the honesty guard (59 rows -> no Calibration), missing-confidence guard,
and report byte-determinism.
"""
from __future__ import annotations

import json

import pytest

from turnstile_quality.calibration import (
    Calibration,
    clear_calibrations,
    judge_may_score,
    register_calibration,
)
from turnstile_quality.calibration_study import (
    BINNING_RULE,
    build_calibration,
    cohens_kappa,
    confusion_matrix,
    expected_calibration_error,
    load_and_register,
    write_report,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_calibrations()
    yield
    clear_calibrations()


def _row(dim, ref, conf, hum):
    return {
        "dim_id": dim,
        "reference_label": ref,
        "reference_confidence": conf,
        "human_label": hum,
    }


# --- cohens_kappa -----------------------------------------------------------

def test_kappa_perfect_agreement_is_one():
    a = ["pass"] * 40 + ["fail"] * 20
    assert cohens_kappa(a, list(a)) == 1.0


def test_kappa_published_worked_example():
    """McHugh (2012), 'Interrater reliability: the kappa statistic',
    Biochemia Medica 22(3):276-282, Table 2: 100 paired ratings with cells
    both-yes=45, A-yes/B-no=15, A-no/B-yes=10, both-no=30.

    Hand computation: po = (45+30)/100 = 0.75;
    pe = (60/100)(55/100) + (40/100)(45/100) = 0.33 + 0.18 = 0.51;
    kappa = (0.75 - 0.51) / (1 - 0.51) = 0.24/0.49 ~= 0.4898.
    """
    a = ["yes"] * 60 + ["no"] * 40
    b = ["yes"] * 45 + ["no"] * 15 + ["yes"] * 10 + ["no"] * 30
    assert cohens_kappa(a, b) == pytest.approx(0.24 / 0.49, abs=1e-9)


def test_kappa_chance_agreement_is_zero():
    a = ["pass"] * 50 + ["fail"] * 50
    b = ["pass", "fail"] * 50  # every cell of the 2x2 holds exactly 25
    assert cohens_kappa(a, b) == pytest.approx(0.0, abs=1e-12)


def test_kappa_rejects_mismatched_or_empty():
    with pytest.raises(ValueError):
        cohens_kappa(["pass"], ["pass", "fail"])
    with pytest.raises(ValueError):
        cohens_kappa([], [])


# --- expected_calibration_error ---------------------------------------------

def test_ece_perfect_calibration_is_zero():
    ece = expected_calibration_error(
        [1.0, 1.0, 0.0, 0.0], [True, True, False, False], n_bins=10
    )
    assert ece == pytest.approx(0.0, abs=1e-12)


def test_ece_hand_computed_two_bin_example():
    """n_bins=2 -> boundary at 0.5; no item sits on it.
    Bin [0, 0.5): {0.4/F} -> |0 - 0.4| * 1/4 = 0.100.
    Bin [0.5, 1.0]: {0.9/T, 0.8/F, 0.6/T} -> acc = 2/3, conf = 2.3/3,
      |2/3 - 2.3/3| * 3/4 = 0.1 * 0.75 = 0.075.
    ECE = 0.100 + 0.075 = 0.175.
    """
    ece = expected_calibration_error(
        [0.9, 0.8, 0.6, 0.4],
        [True, False, True, False],
        n_bins=2,
    )
    assert ece == pytest.approx(0.175, abs=1e-9)


def test_ece_confidence_one_falls_in_last_bin():
    ece = expected_calibration_error([1.0], [True], n_bins=10)
    assert ece == pytest.approx(0.0, abs=1e-12)


def test_ece_rejects_bad_input():
    with pytest.raises(ValueError):
        expected_calibration_error([0.5], [True, False])
    with pytest.raises(ValueError):
        expected_calibration_error([], [])
    with pytest.raises(ValueError):
        expected_calibration_error([1.5], [True])
    with pytest.raises(ValueError):
        expected_calibration_error([0.5], [True], n_bins=0)


# --- confusion_matrix --------------------------------------------------------

def test_confusion_matrix_counts():
    a = ["pass", "pass", "fail", "fail"]
    b = ["pass", "fail", "pass", "fail"]
    assert confusion_matrix(a, b) == {"tp": 1, "tn": 1, "fp": 1, "fn": 1}


def test_confusion_matrix_rejects_non_binary():
    with pytest.raises(ValueError):
        confusion_matrix(["pass", "maybe"], ["pass", "pass"])


# --- build_calibration -------------------------------------------------------

def _passing_rows(dim="faithfulness"):
    """60 rows, 54 agreements, balanced marginals: po=0.9, pe=0.5 -> kappa=0.8."""
    rows = []
    rows += [_row(dim, "pass", 0.85, "pass") for _ in range(27)]
    rows += [_row(dim, "fail", 0.85, "fail") for _ in range(27)]
    rows += [_row(dim, "pass", 0.6, "fail") for _ in range(3)]
    rows += [_row(dim, "fail", 0.6, "pass") for _ in range(3)]
    return rows


def test_build_calibration_happy_path():
    rows = _passing_rows()
    cal, info = build_calibration("faithfulness", rows)
    assert isinstance(cal, Calibration)
    assert cal.n_labels == 60
    assert cal.kappa == pytest.approx(0.8, abs=1e-9)
    assert cal.ece is not None
    assert info["passes_gate"] is True
    assert info["shortfall"] is None
    assert info["confusion_matrix"] == {"tp": 27, "tn": 27, "fp": 3, "fn": 3}


def test_build_calibration_uses_only_checked_rows_of_this_dim():
    rows = _passing_rows("faithfulness")
    rows += [_row("faithfulness", "pass", 0.9, None) for _ in range(10)]  # unchecked
    rows += [_row("answer_relevance", "pass", 0.9, "pass") for _ in range(60)]
    cal, info = build_calibration("faithfulness", rows)
    assert cal is not None and cal.n_labels == 60
    cal2, _ = build_calibration("answer_relevance", rows)
    assert cal2 is not None and cal2.n_labels == 60


def test_build_calibration_insufficient_data_guard():
    rows = _passing_rows()[:59]  # one short of the 60-label bar
    cal, info = build_calibration("faithfulness", rows)
    assert cal is None
    assert info["n_labels"] == 59
    assert info["passes_gate"] is False
    assert "59" in info["shortfall"] and "60" in info["shortfall"]


def test_build_calibration_missing_confidence_guard():
    rows = _passing_rows()
    rows[0] = _row("faithfulness", "pass", None, "pass")
    cal, info = build_calibration("faithfulness", rows)
    assert cal is None
    assert info["passes_gate"] is False
    assert "confidence" in info["shortfall"]


def test_build_calibration_below_bar_kappa_still_reported_honestly():
    rows = [_row("faithfulness", "pass", 0.6, "pass") for _ in range(30)]
    rows += [_row("faithfulness", "pass", 0.6, "fail") for _ in range(30)]
    cal, info = build_calibration("faithfulness", rows)
    assert cal is not None  # honest numbers returned; the GATE refuses, not the builder
    assert cal.kappa < 0.75
    assert info["passes_gate"] is False
    assert info["shortfall"] is None


# --- write_report / load_and_register ----------------------------------------

FIXED_TS = "2026-09-17T00:00:00+00:00"


def test_report_determinism_same_labels_identical_bytes(tmp_path):
    per_dim = {
        "faithfulness": build_calibration("faithfulness", _passing_rows()),
    }
    p1 = tmp_path / "r1.json"
    p2 = tmp_path / "r2.json"
    kwargs = {"labels_sha256": "abc123", "generated_at": FIXED_TS}
    write_report(p1, per_dim, **kwargs)
    write_report(p2, per_dim, **kwargs)
    assert p1.read_bytes() == p2.read_bytes()
    data = json.loads(p1.read_text(encoding="utf-8"))
    entry = data["dimensions"]["faithfulness"]
    assert entry["n_labels"] == 60
    assert entry["kappa"] == pytest.approx(0.8, abs=1e-6)
    assert entry["ece"] is not None
    assert entry["confusion_matrix"] == {"tp": 27, "tn": 27, "fp": 3, "fn": 3}
    assert entry["passes_gate"] is True
    assert data["binning_rule"] == BINNING_RULE
    assert data["tool_version"] and data["labels_sha256"] == "abc123"


def test_report_states_shortfall_honestly(tmp_path):
    per_dim = {
        "faithfulness": build_calibration("faithfulness", _passing_rows()[:59]),
    }
    path = tmp_path / "report.json"
    write_report(path, per_dim, labels_sha256="deadbeef", generated_at=FIXED_TS)
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["dimensions"]["faithfulness"]
    assert entry["passes_gate"] is False
    assert entry["kappa"] is None and entry["ece"] is None
    assert "59" in entry["shortfall"]


def test_load_and_register_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    per_dim = {
        "faithfulness": build_calibration("faithfulness", _passing_rows()),
        "answer_relevance": build_calibration("answer_relevance", _passing_rows()[:59]),
    }
    path = tmp_path / "report.json"
    write_report(path, per_dim, labels_sha256="x", generated_at=FIXED_TS)
    load_and_register(path)
    assert judge_may_score("faithfulness") is True
    # Shortfall dimension registers nothing: the gate stays honestly closed.
    assert judge_may_score("answer_relevance") is False


def test_load_and_register_uses_public_api_only(monkeypatch, tmp_path):
    """A passing-shaped report for an unknown dim must surface CalibrationError."""
    from turnstile_quality.calibration import CalibrationError

    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    register_calibration("faithfulness", Calibration(n_labels=60, kappa=0.9, ece=0.05))
    per_dim = {
        "invented_dimension": (
            Calibration(n_labels=60, kappa=0.9, ece=0.05),
            {
                "n_labels": 60,
                "kappa": 0.9,
                "ece": 0.05,
                "confusion_matrix": {"tp": 1, "tn": 0, "fp": 0, "fn": 0},
                "passes_gate": True,
                "shortfall": None,
            },
        ),
    }
    path = tmp_path / "report.json"
    write_report(path, per_dim, labels_sha256="x", generated_at=FIXED_TS)
    with pytest.raises(CalibrationError):
        load_and_register(path)
