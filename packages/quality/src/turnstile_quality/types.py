"""Quality-eval layer (PRD 04): quality reported BESIDE cost, never instead of it.

A focused, voice-aware rubric that pairs with the cost/margin wedge. Every
dimension carries an honesty tier in the same vocabulary as METHOD.md:

* ``measured`` -- deterministic rule over data the trace/verdict already
  carry. Scores 1.0 (pass), 0.5 (partial), 0.0 (fail).
* ``instrumented`` -- the check is defined but this input lacks the data to
  run it (same pattern as the pipeline's acoustic-absence envelope).
  Score None, label ``unmeasured``.
* ``not_measured`` -- needs a calibrated model judge that does not exist yet
  (see ``calibration.py``). Score None, label ``pending``.

No frozen-schema change: these types live here in ``turnstile_quality``,
not in ``turnstile_schema``. No network, no model calls, no randomness --
the default path is pure and deterministic.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")

Tier = Literal["measured", "instrumented", "not_measured"]
Method = Literal["deterministic", "judge_calibrated", "judge_pending"]
DimensionLabel = Literal["pass", "partial", "fail", "unmeasured", "pending"]

#: Score convention for deterministic dimensions: rule outcome as a number.
SCORE_PASS = 1.0
SCORE_PARTIAL = 0.5
SCORE_FAIL = 0.0


class QualityDimension(BaseModel):
    """One rubric dimension: id, score (None when unscored), label, tier,
    evidence, and how it was produced."""

    model_config = _STRICT
    id: str
    score: float | None
    label: DimensionLabel
    tier: Tier
    evidence: dict = Field(default_factory=dict)
    method: Method


class QualityOverall(BaseModel):
    """Call-level roll-up over the SCORABLE dimensions only.

    Pending judge dimensions never feed this (mirroring how an inferred
    ``decision_kind`` never feeds a measured D1): ``pending`` is absence of
    measurement, not a vote. ``tier`` is ``measured`` whenever at least one
    measured dimension scored, which is always the case today.
    """

    model_config = _STRICT
    label: Literal["pass", "partial", "fail"]
    tier: Tier


class QualityReport(BaseModel):
    """The per-call quality block: dimensions + overall + report evidence."""

    model_config = _STRICT
    dimensions: list[QualityDimension]
    overall: QualityOverall
    evidence: list[dict] = Field(default_factory=list)

    def by_id(self, dim_id: str) -> QualityDimension:
        """Fetch one dimension by id (KeyError with the id when absent)."""
        for dim in self.dimensions:
            if dim.id == dim_id:
                return dim
        raise KeyError(f"quality dimension {dim_id!r} not in report")
