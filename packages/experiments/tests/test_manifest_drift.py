"""Tests for the manifest-drift report (batch 2 T5): reproducible rows, and
the READ-ONLY guarantee -- regenerating the report never writes to
fixtures/golden/ (that is owner lane)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "manifest_drift_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("manifest_drift_report", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _golden_snapshot() -> dict[str, bytes]:
    golden = Path(__file__).resolve().parents[3] / "fixtures" / "golden"
    return {p.name: p.read_bytes() for p in sorted(golden.rglob("*")) if p.is_file()}


def test_drift_rows_cover_every_manifest_fixture():
    mod = _load()
    rows = mod._drift_rows()
    assert len(rows) == 23
    assert all({"id", "manifest", "adjudicated", "match"} <= set(r) for r in rows)


def test_regeneration_is_read_only_over_fixtures_and_reproducible():
    mod = _load()
    before = _golden_snapshot()
    rows = mod._drift_rows()
    assert _golden_snapshot() == before  # READ-ONLY: nothing under golden moved

    # Reproducible: every committed report row matches a fresh regeneration.
    committed = mod.OUT_PATH.read_text(encoding="utf-8")
    assert "READ-ONLY diff for the owner" in committed
    for r in rows:
        line = (
            f"| {r['id']} | {r['manifest']} | {r['adjudicated']} "
            f"| {'yes' if r['match'] else '**NO**'} |"
        )
        assert line in committed, line
    drifters = [r for r in rows if not r["match"]]
    assert f"**{len(drifters)} of {len(rows)} fixtures drift**" in committed


def test_no_drift_after_application():
    # The drift report was applied: the manifest's expected_verdict was aligned
    # to adjudicate()'s output for all 23 fixtures (and test_adjudicate.py now
    # pins the full set). So the drift set is EMPTY -- any future verdict or
    # manifest change surfaces here as a new drifter (and fails test_adjudicate).
    mod = _load()
    drifters = {r["id"] for r in mod._drift_rows() if not r["match"]}
    assert drifters == set()