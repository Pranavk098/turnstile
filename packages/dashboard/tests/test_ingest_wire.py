"""W3 Item 5 -- the ingested report is wired into the dashboard.

The build publishes the committed turnstile_ingest artifact into sample/
(no recomputation, no hardcoded numbers); the manifest points at it; the
dashboard renders it end-to-end (fleet + 7-call list -> per-call
drill-down) with D6/D7/D8 honestly ABSENT and every margin number stamped
with its dataset. Static assertions on JSON + HTML (no browser in CI)."""
from __future__ import annotations

import json

import pytest

import build_data


def _dashboard(name: str) -> dict:
    return json.loads(
        (build_data.DASHBOARD_DIR / "sample" / name).read_text(encoding="utf-8"))


def _ingest_artifact() -> dict:
    return json.loads(build_data.INGEST_SOURCE_FILE.read_text(encoding="utf-8"))


def _html() -> str:
    return (build_data.DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 5.1 -- the ingest report is published + the manifest points at it.           #
# --------------------------------------------------------------------------- #

def test_manifest_declares_the_ingest_report_available():
    manifest = _dashboard("manifest.json")
    hook = manifest["ingest"]
    assert hook["status"] == "available"
    assert hook["report_path"] == "sample/ingest.json"
    assert (build_data.DASHBOARD_DIR / hook["report_path"]).exists()


def test_published_report_reads_the_artifact_verbatim():
    # No hardcoded numbers: sample/ingest.json IS packages/ingest/data/data.json.
    assert _dashboard("ingest.json") == _ingest_artifact()


def test_build_ingest_copies_artifact_and_details(tmp_path):
    hook = build_data.build_ingest(tmp_path)
    assert hook == {"status": "available", "report_path": "sample/ingest.json"}
    artifact = _ingest_artifact()
    assert json.loads((tmp_path / "ingest.json").read_text(encoding="utf-8")) == artifact
    for row in artifact["calls"]:
        detail = json.loads((tmp_path / row["detail"]).read_text(encoding="utf-8"))
        assert detail["conv_cost"] == pytest.approx(row["cost_usd"])


def test_ingest_report_renders_end_to_end_shapes():
    report = _dashboard("ingest.json")
    assert report["n"] == 7 and len(report["calls"]) == 7
    assert report["fleet"]["n_conversations"] == 7
    for row in report["calls"]:
        assert set(row) == set(build_data.INGEST_CONTRACT["index_row_keys"])
        top = row["top_waste"]
        assert top is None or set(top) == {"class_id", "waste_usd", "span_id", "turn_index"}
        detail = _dashboard(row["detail"])
        for key in build_data.INGEST_CONTRACT["detail_keys"]:
            assert key in detail, (row["id"], key)
        assert detail["conv_cost"] == pytest.approx(row["cost_usd"])
        assert detail["verdict"]["label"] == row["verdict"]
        assert detail["trace"]["conversation"]["scenario_id"] == row["scenario_id"]
    hero = max(
        (r for r in report["calls"] if r["top_waste"] is not None),
        key=lambda r: r["top_waste"]["waste_usd"],
        default=report["calls"][0],
    )
    assert hero["id"] == "ing-20260904-007"


# --------------------------------------------------------------------------- #
# 5.2 -- HONEST acoustic absence: D6/D7/D8 absent with reason, never zeroed.   #
# --------------------------------------------------------------------------- #

def test_ingest_data_marks_6_7_8_absent_and_carries_no_6_7_8_findings():
    report = _dashboard("ingest.json")
    summary = report["coverage_summary"]
    assert summary["n_calls"] == 7
    with_data = summary["calls_with_data_per_class"]
    for cid in ("1", "2", "3", "4", "5", "9", "10"):
        assert with_data.get(cid, 0) == 7, cid
    for cid in ("6", "7", "8"):
        assert with_data.get(cid, 0) == 0, cid
    assert not any(f["class_id"] in (6, 7, 8) for f in report["findings"])
    for row in report["calls"]:
        detail = _dashboard(row["detail"])
        coverage = detail["_provenance"]["coverage"]
        assert len(coverage) == 10
        for cid in ("6", "7", "8"):
            assert coverage[cid]["status"] == "absent"
            assert "no data for this input" in coverage[cid]["reason"]
        for cid in ("1", "2", "3", "4", "5", "9", "10"):
            assert coverage[cid]["status"] == "present"
        assert not any(f["class_id"] in (6, 7, 8) for f in detail["findings"])


def test_dashboard_shows_absence_never_zeroed():
    html = _html()
    # Fleet + per-call coverage strips, fed by the report (never hardcoded).
    assert 'id="findings-coverage"' in html
    assert 'id="hero-coverage"' in html
    assert "coverageSplit(" in html
    assert "coverage_summary" in html
    # Absent classes render as muted ABSENT rows: no bar, no dollar figure.
    assert "absent-row" in html
    assert "absent — no data for this input" in html
    absent_section = html.split("absent-row")[1].split("function renderCallsList(")[0]
    assert "fill" not in absent_section
    assert "fmtMoney" not in absent_section
    # Per-call empty findings distinguish absent from clean.
    assert "no waste detected among measured classes" in html
    assert "every detector came back clean" in html  # golden path unchanged


# --------------------------------------------------------------------------- #
# 5.3 -- dataset-labeled margin: (n, dataset) on the number, no cross-talk.   #
# --------------------------------------------------------------------------- #

def test_ingest_margin_stamped_with_its_dataset():
    report = _dashboard("ingest.json")
    margin = report["fleet"]["recoverable_margin_pct"]
    assert margin == pytest.approx(2.69, abs=0.005)
    assert report["fleet"]["_provenance"]["n"] == 7
    # No provenance text cites a different dataset's number than displayed.
    blob = json.dumps(report)
    assert "1.32" not in blob and "0.57" not in blob
    assert "23 golden" not in blob


def test_dashboard_stamps_every_margin_with_its_dataset():
    html = _html()
    assert "Over these " in html
    assert '"ingest calls"' in html and '"golden-fixture calls"' in html
    assert "renderDataset(" in html
    assert "viewing:" in html


def test_home_proven_number_carries_its_dataset():
    home = (build_data.DASHBOARD_DIR / "home.html").read_text(encoding="utf-8")
    fleet = _dashboard("fleet.json")
    assert f"{fleet['recoverable_margin_pct']:.2f}<small>%</small>" in home
    assert f"these {fleet['n_conversations']} golden-fixture calls" in home


# --------------------------------------------------------------------------- #
# 5.1 (UI) -- the dashboard reads the manifest + switches sources.            #
# --------------------------------------------------------------------------- #

def test_dashboard_reads_manifest_and_switches_sources():
    html = _html()
    assert 'loadJSON("sample/manifest.json")' in html
    assert "loadOptional(ingestPath)" in html
    assert 'id="source-switch"' in html
    assert 'data-source="ingest"' in html and 'data-source="golden"' in html
    assert "ingestHeroId(" in html
    # Golden fixtures stay available as the default source.
    assert "Golden fixtures" in html
    # The honest fallback survives for a missing artifact.
    assert "is not wired yet" in html
    # Drill-down routing resolves ingest detail filenames already on disk.
    assert "sample/call-" in html
    report = _dashboard("ingest.json")
    sample = build_data.DASHBOARD_DIR / "sample"
    for row in report["calls"]:
        assert (sample / row["detail"]).exists()
