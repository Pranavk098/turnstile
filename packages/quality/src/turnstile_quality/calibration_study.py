"""Calibration statistics + report builder for judge dimensions (Day-4 Part B).

Pure-stdlib module: no network imports (the ``test_no_network_imports_in_quality_package``
gate bans them in this package). All math here is deterministic.

Row schema (duck-typed mapping; Part A's label records satisfy it, but this module
does NOT import Part A's files so the two parts stay decoupled):

    {
        "dim_id": str,                # e.g. "faithfulness" / "answer_relevance"
        "reference_label": "pass" | "fail" | None,   # paid pre-label (Part E)
        "reference_confidence": float in [0, 1] | None,  # needed for ECE
        "human_label": "pass" | "fail" | None,       # rater verdict; None = unchecked
    }

Only rows with ``human_label`` set count toward ``n_labels``. ``kappa`` is
reference-vs-human agreement; ``ece`` compares ``reference_confidence`` against
correctness (``reference_label == human_label``).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from turnstile_quality.calibration import (
    MIN_CALIBRATION_KAPPA,
    MIN_CALIBRATION_LABELS,
    Calibration,
    register_calibration,
)

#: Tool version stamped into every report (mirrors packages/quality/pyproject.toml).
TOOL_VERSION = "0.0.0"

#: Default ECE bin count.
DEFAULT_N_BINS = 10

#: Number of decimal places floats are rounded to in the written report.
REPORT_FLOAT_NDIGITS = 6

#: Binning rule, recorded verbatim in every report so ECE is re-derivable.
BINNING_RULE = (
    "equal-width ECE with n_bins bins over [0, 1]: bin index for confidence c is "
    "min(int(c * n_bins), n_bins - 1), so bin i covers [i/n_bins, (i+1)/n_bins) "
    "except the last bin which includes c == 1.0; "
    "ECE = sum_b (|B_b| / N) * |acc(B_b) - conf(B_b)| "
    "where acc is the fraction of correct items and conf the mean confidence in "
    "bin b; empty bins contribute 0."
)

_PASS = "pass"
_FAIL = "fail"


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """Two-rater categorical agreement (Cohen 1960).

    ``(po - pe) / (1 - pe)`` where ``po`` is observed agreement and ``pe`` the
    chance-expected agreement from the raters' marginal distributions.
    Raises ``ValueError`` on length mismatch or empty input. When all ratings
    fall in a single category (``pe == 1``) the ratio is undefined: returns 1.0
    for perfect agreement, else 0.0.
    """
    if len(a) != len(b):
        raise ValueError(f"raters disagree in length: {len(a)} != {len(b)}")
    n = len(a)
    if n == 0:
        raise ValueError("need at least one paired rating")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca = Counter(a)
    cb = Counter(b)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in set(ca) | set(cb))
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def expected_calibration_error(
    confidences: list[float], correct: list[bool], n_bins: int = 10
) -> float:
    """Equal-width-bin ECE (see BINNING_RULE). 0.0 == perfectly calibrated.

    Raises ``ValueError`` on length mismatch, empty input, ``n_bins < 1``, or a
    confidence outside [0, 1].
    """
    if len(confidences) != len(correct):
        raise ValueError(
            f"length mismatch: {len(confidences)} != {len(correct)}"
        )
    n = len(confidences)
    if n == 0:
        raise ValueError("need at least one prediction")
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")
    for c in confidences:
        if not 0.0 <= c <= 1.0:
            raise ValueError(f"confidence {c!r} outside [0, 1]")
    bin_correct = [0] * n_bins
    bin_conf_sum = [0.0] * n_bins
    bin_count = [0] * n_bins
    for c, ok in zip(confidences, correct):
        b = min(int(c * n_bins), n_bins - 1)
        bin_count[b] += 1
        bin_conf_sum[b] += c
        bin_correct[b] += 1 if ok else 0
    ece = 0.0
    for b in range(n_bins):
        if bin_count[b]:
            acc = bin_correct[b] / bin_count[b]
            conf = bin_conf_sum[b] / bin_count[b]
            ece += (bin_count[b] / n) * abs(acc - conf)
    return ece


def confusion_matrix(a: list[str], b: list[str]) -> dict[str, int]:
    """2x2 pass/fail agreement counts.

    First list is the reference (predicted), second the human (actual);
    "pass" is the positive class: tp = both pass, tn = both fail,
    fp = reference pass / human fail, fn = reference fail / human pass.
    Raises ``ValueError`` on length mismatch or non pass/fail labels.
    """
    if len(a) != len(b):
        raise ValueError(f"length mismatch: {len(a)} != {len(b)}")
    for x, y in zip(a, b):
        if x not in (_PASS, _FAIL) or y not in (_PASS, _FAIL):
            raise ValueError(f"confusion matrix needs pass/fail labels, got {x!r}, {y!r}")
    matrix = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for x, y in zip(a, b):
        if x == _PASS and y == _PASS:
            matrix["tp"] += 1
        elif x == _FAIL and y == _FAIL:
            matrix["tn"] += 1
        elif x == _PASS and y == _FAIL:
            matrix["fp"] += 1
        else:
            matrix["fn"] += 1
    return matrix


def _round6(x: float | None) -> float | None:
    return None if x is None else round(float(x), REPORT_FLOAT_NDIGITS)


def build_calibration(
    dim_id: str, rows: list[Mapping[str, Any]]
) -> tuple[Calibration | None, dict[str, Any]]:
    """Build a ``Calibration`` for ``dim_id`` from label rows.

    Uses ONLY rows whose ``dim_id`` matches and whose ``human_label`` is set.
    Returns ``(calibration, info)`` where ``info`` always carries ``n_labels``,
    ``kappa``, ``ece``, ``confusion_matrix``, ``passes_gate`` and ``shortfall``.

    HONESTY GUARD: if fewer than 60 human-checked rows exist, or any checked
    row lacks ``reference_label``/``reference_confidence``, returns
    ``(None, info)`` with ``info["shortfall"]`` stating the actual counts.
    Never pads, never imputes.
    """
    checked = [
        r
        for r in rows
        if r.get("dim_id") == dim_id and r.get("human_label") is not None
    ]
    n = len(checked)

    def _shortfall(reason: str) -> tuple[None, dict[str, Any]]:
        return None, {
            "dim_id": dim_id,
            "n_labels": n,
            "kappa": None,
            "ece": None,
            "confusion_matrix": None,
            "passes_gate": False,
            "shortfall": reason,
        }

    if n < MIN_CALIBRATION_LABELS:
        return _shortfall(
            f"insufficient human-checked rows for {dim_id!r}: "
            f"n_labels={n} < {MIN_CALIBRATION_LABELS} required; "
            "gate stays closed (no padding, no imputation)."
        )
    missing_ref = sum(1 for r in checked if r.get("reference_label") is None)
    missing_conf = sum(1 for r in checked if r.get("reference_confidence") is None)
    if missing_ref or missing_conf:
        return _shortfall(
            f"missing reference data for {dim_id!r}: n_labels={n}, "
            f"{missing_ref} rows lack reference_label, "
            f"{missing_conf} rows lack reference_confidence; "
            "ECE/kappa need complete reference data, gate stays closed."
        )
    ref = [r["reference_label"] for r in checked]
    hum = [r["human_label"] for r in checked]
    kappa = cohens_kappa(ref, hum)
    correct = [rv == hv for rv, hv in zip(ref, hum)]
    ece = expected_calibration_error(
        [float(r["reference_confidence"]) for r in checked],
        correct,
        DEFAULT_N_BINS,
    )
    cal = Calibration(n_labels=n, kappa=kappa, ece=ece)
    passes = (
        cal.n_labels >= MIN_CALIBRATION_LABELS
        and cal.kappa >= MIN_CALIBRATION_KAPPA
        and cal.ece is not None
    )
    return cal, {
        "dim_id": dim_id,
        "n_labels": n,
        "kappa": kappa,
        "ece": ece,
        "confusion_matrix": confusion_matrix(ref, hum),
        "passes_gate": passes,
        "shortfall": None,
    }


def write_report(
    path: str | Path,
    per_dim: Mapping[str, tuple[Calibration | None, dict[str, Any]]],
    *,
    labels_sha256: str = "",
    labels_path: str | Path | None = None,
    tool_version: str = TOOL_VERSION,
    generated_at: str | None = None,
    binning_rule: str = BINNING_RULE,
) -> None:
    """Write the calibration report JSON (default target fixtures/calibration/calibration_report.json).

    ``per_dim`` maps dim_id -> the ``(calibration, info)`` pair returned by
    :func:`build_calibration`. Byte-deterministic given the same inputs:
    ``sort_keys=True``, 2-space indent, trailing newline, floats rounded to
    6 decimals. Pass ``labels_path`` to hash the committed labels file into
    provenance, or ``labels_sha256`` directly; pass a fixed ``generated_at``
    for reproducible bytes (defaults to current UTC time).
    """
    if labels_path is not None and not labels_sha256:
        labels_sha256 = hashlib.sha256(
            Path(labels_path).read_bytes()
        ).hexdigest()
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()
    dimensions: dict[str, Any] = {}
    for dim_id in sorted(per_dim):
        _cal, info = per_dim[dim_id]
        cm = info.get("confusion_matrix")
        dimensions[dim_id] = {
            "confusion_matrix": dict(cm) if cm is not None else None,
            "ece": _round6(info.get("ece")),
            "kappa": _round6(info.get("kappa")),
            "n_labels": info.get("n_labels"),
            "passes_gate": bool(info.get("passes_gate")),
            "shortfall": info.get("shortfall"),
        }
    report = {
        "binning_rule": binning_rule,
        "dimensions": dimensions,
        "generated_at": generated_at,
        "labels_sha256": labels_sha256,
        "tool_version": tool_version,
    }
    Path(path).write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def load_and_register(report_path: str | Path) -> None:
    """Register each sufficiently-measured dimension from a committed report.

    Calls the existing public ``register_calibration`` with a ``Calibration``
    rebuilt from the report's numbers. Dimensions whose report entry has a
    shortfall (``kappa``/``ece`` null) are SKIPPED -- nothing is registered for
    them, so ``judge_may_score`` stays False and the gate stays honestly closed.
    """
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    for dim_id in sorted(data["dimensions"]):
        entry = data["dimensions"][dim_id]
        if entry.get("kappa") is None or entry.get("ece") is None:
            continue
        register_calibration(
            dim_id,
            Calibration(
                n_labels=int(entry["n_labels"]),
                kappa=float(entry["kappa"]),
                ece=float(entry["ece"]),
            ),
        )
