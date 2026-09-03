"""Tests for the dashboard's data builder (batch 2 T3/T4).

The load-bearing assertions: the barge-in panel's numbers TRACE to the
harness report (nothing recomputed or hardcoded), the provenance string is
carried through verbatim, and index.html carries the panel + its embedded
file:// fallback in sync."""
from __future__ import annotations

import json

import pytest
from turnstile_corpus.distributions import BARGE_IN_RATE
from turnstile_agent import FakeEngine
from turnstile_experiments import run_bargein_report

import build_data


# --------------------------------------------------------------------------- #
# The barge-in headline panel traces to the harness report.                    #
# --------------------------------------------------------------------------- #

def _small_report(**kwargs):
    return run_bargein_report(
        FakeEngine(), rates_values=[0.0, BARGE_IN_RATE, 0.3], n=12, seed=3, **kwargs)


def test_bargein_panel_traces_to_the_report_verbatim():
    report = _small_report()
    panel = build_data.build_bargein(report)
    # Nothing recomputed: every table IS the report's own data.
    assert panel["rate_sweep"] == report["points"]
    assert panel["lead_cap_sweep"] == report["lead_cap_sweep"]
    assert panel["granularity_sweep"] == report["granularity_sweep"]
    assert panel["provenance"] == report["provenance"]
    assert panel["n"] == report["n"] and panel["seed"] == report["seed"]
    # The headline IS the report's point at the cited default rate.
    assert panel["headline"] == next(
        p for p in report["points"] if p["barge_in_rate"] == BARGE_IN_RATE)
    assert panel["headline"]["waste_share_of_tts_spend"] > 0.0
    assert "measured" in panel["label"].lower()


def test_bargein_panel_requires_the_cited_rate_point():
    report = run_bargein_report(FakeEngine(), rates_values=[0.05, 0.10], n=6, seed=1)
    with pytest.raises(ValueError, match="cited default rate"):
        build_data.build_bargein(report)


def test_bargein_panel_floor_annotation_comes_from_the_report_points():
    report = _small_report()
    panel = build_data.build_bargein(report)
    fl = panel["floor_annotation"]
    if fl is not None:  # a flat run exists in this report -> it must trace
        pts = report["lead_cap_sweep"]["points"]
        assert any(
            p["lead_cap_s"] == fl["from"] and p["waste_share_of_tts_spend"] == fl["value"]
            for p in pts
        )
        assert fl["to"] >= fl["from"]
        assert "floor" in fl["note"]


def test_flat_run_detector_finds_the_measured_floor():
    points = [
        {"lead_cap_s": 0.5, "waste_share_of_tts_spend": 0.041},
        {"lead_cap_s": 1.0, "waste_share_of_tts_spend": 0.041},
        {"lead_cap_s": 2.0, "waste_share_of_tts_spend": 0.041},
        {"lead_cap_s": 3.0, "waste_share_of_tts_spend": 0.044},
    ]
    fl = build_data._flat_run(points, "lead_cap_s", "waste_share_of_tts_spend")
    assert fl == {
        "from": 0.5, "to": 2.0, "value": 0.041,
        "note": build_data._flat_run(points, "lead_cap_s", "waste_share_of_tts_spend")["note"],
    }
    assert build_data._flat_run(points[:1], "lead_cap_s", "waste_share_of_tts_spend") is None


def test_load_bargein_report_fails_loud_when_missing(tmp_path):
    with pytest.raises(SystemExit, match="run_bargein_harness"):
        build_data.load_bargein_report(tmp_path / "missing.json")


# --------------------------------------------------------------------------- #
# index.html: the panel exists and the embedded file:// fallback stays in sync.#
# --------------------------------------------------------------------------- #

def test_index_html_carries_the_bargein_panel_and_embed():
    html = build_data.INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="bargein"' in html
    assert 'id="data-bargein"' in html
    assert "renderBargein(" in html
    assert "sample/bargein.sample.json" in html
    # The embed id is registered so sync_embedded_json keeps it from drifting.
    assert "data-bargein" in build_data._EMBED_IDS


def test_sync_embedded_json_updates_the_bargein_block(tmp_path):
    html = (
        '<html><body><script type="application/json" id="data-bargein">\n'
        "{}\n</script></body></html>"
    )
    target = tmp_path / "index.html"
    target.write_text(html, encoding="utf-8")
    original = build_data.INDEX_HTML
    build_data.INDEX_HTML = target
    try:
        build_data.sync_embedded_json({"data-bargein": {"label": "x", "v": 1}})
    finally:
        build_data.INDEX_HTML = original
    synced = json.loads(
        target.read_text(encoding="utf-8").split('id="data-bargein">\n')[1]
        .split("\n</script>")[0]
    )
    assert synced == {"label": "x", "v": 1}