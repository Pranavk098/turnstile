"""Calibration gate for model-graded quality dimensions (PRD 04 §3.2).

The discipline mirrors verdict evidence-source 5 (a deliberate no-op until
calibrated) and LIMITATIONS.md §6 (60 hand labels + Cohen's κ ≥ 0.75):

* A judge dimension may emit a score only when ``judge_may_score(dim_id)``
  returns True: the paid flag is set (judges are never free-tier), a
  calibration is registered for that dimension, and it meets n ≥ 60,
  κ ≥ 0.75, with ECE reported.
* No judge implementation ships yet (out of scope per PRD §9), so nothing
  can reach the scoring path today even with the flag set -- the gate is
  tested as pure logic, and ``evaluate_quality`` always reports pending.

Mutable registry, lock-guarded: calibration is a rare administrative write
(once per calibration study), reads happen per eval.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

#: Dimensions that genuinely need a model (PRD 04 §4.2). Closed set: a typo'd
#: id can never open a gate (register_calibration rejects unknown ids).
JUDGE_DIMENSIONS = ("faithfulness", "answer_relevance")

MIN_CALIBRATION_LABELS = 60
MIN_CALIBRATION_KAPPA = 0.75

PAID_FLAG_ENV = "TURNSTILE_ALLOW_PAID"


@dataclass(frozen=True)
class Calibration:
    """One calibration study for a judge dimension."""

    n_labels: int
    kappa: float
    ece: float | None


_CALIBRATIONS: dict[str, Calibration] = {}
_LOCK = threading.Lock()


class CalibrationError(ValueError):
    """A calibration was registered, requested, or scored unlawfully."""


def register_calibration(dim_id: str, calibration: Calibration) -> None:
    """Record a calibration study for a judge dimension.

    Raises ``CalibrationError`` for unknown dimension ids -- a misspelled id
    must never silently create a gate that nothing checks.
    """
    if dim_id not in JUDGE_DIMENSIONS:
        raise CalibrationError(
            f"unknown judge dimension {dim_id!r} "
            f"(known: {', '.join(JUDGE_DIMENSIONS)})"
        )
    with _LOCK:
        _CALIBRATIONS[dim_id] = calibration


def clear_calibrations() -> None:
    """Forget all registered calibrations (tests only)."""
    with _LOCK:
        _CALIBRATIONS.clear()


def judge_may_score(dim_id: str) -> bool:
    """The §3.2 gate, as pure logic: paid flag on AND a registered
    calibration meeting n ≥ 60, κ ≥ 0.75, ECE reported. Anything else --
    including an unknown id -- is False. No score can be emitted without this
    returning True, and no judge implementation exists yet to call it."""
    if os.environ.get(PAID_FLAG_ENV) != "1":
        return False
    with _LOCK:
        cal = _CALIBRATIONS.get(dim_id)
    if cal is None:
        return False
    return (
        cal.n_labels >= MIN_CALIBRATION_LABELS
        and cal.kappa >= MIN_CALIBRATION_KAPPA
        and cal.ece is not None
    )
