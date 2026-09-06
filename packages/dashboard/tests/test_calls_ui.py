"""W3-B Item 2 -- the explorable UI: a call-list index routes (by hash) to a
per-call detail view, keyboard-accessibly.

Two layers: the shipped sample/*.json must back every index row with a real
detail file, and index.html must carry the list, the router, and the focus
management (real links, aria-current, focus into the detail)."""
from __future__ import annotations

import json

import pytest

import build_data


def _html() -> str:
    return (build_data.DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")


def _calls() -> dict:
    return json.loads(
        (build_data.DASHBOARD_DIR / "sample" / "calls.json").read_text(encoding="utf-8"))


def test_shipped_calls_index_links_to_real_detail_files():
    payload = _calls()
    assert payload["n"] == len(payload["calls"]) == 23
    sample = build_data.DASHBOARD_DIR / "sample"
    for row in payload["calls"]:
        # id . scenario . cost . verdict . top waste -- every column backed.
        for key in ("id", "scenario_id", "cost_usd", "verdict", "top_waste", "detail"):
            assert key in row, (row.get("id"), key)
        detail = json.loads((sample / row["detail"]).read_text(encoding="utf-8"))
        assert detail["conv_cost"] == pytest.approx(row["cost_usd"])
        assert detail["verdict"]["label"] == row["verdict"]
        assert detail["trace"]["conversation"]["scenario_id"] == row["scenario_id"]
        if row["top_waste"] is None:
            assert detail["findings"] == []
    hero = next(r for r in payload["calls"] if r["id"] == payload["hero"])
    assert hero["cost_usd"] > 0


def test_index_html_has_routed_call_list_and_detail():
    html = _html()
    # The list: id . scenario . cost . verdict . top waste.
    assert 'id="calls"' in html
    for header in ("<th>Call</th>", "<th>Scenario</th>", "<th>Cost</th>",
                   "<th>Verdict</th>", "<th>Top waste</th>"):
        assert header in html, header
    assert "sample/calls.json" in html
    # The router: hash-based (static-friendly), per-call fetch, default hero.
    assert "#/call/" in html
    assert "hashchange" in html
    assert "sample/call-" in html
    assert "calls.hero" in html
    # The detail: verdict + flame + per-call findings containers.
    assert 'id="hero-verdict"' in html
    assert 'id="hero-findings"' in html
    assert "renderCallMeta(" in html


def test_call_navigation_is_keyboard_accessible():
    html = _html()
    # Rows navigate with real links (tab-reachable, announced with context).
    assert '<a href="#/call/' in html
    assert "aria-current" in html
    # Following a link moves focus into the detail (not just scrolling).
    assert 'id="hero-title" tabindex="-1"' in html
    assert 'getElementById("hero-title").focus(' in html
    # Plain #fleet-style anchors still work: the router only claims #/call/.
    assert r"/^#\/call\/" in html


def test_ingest_hook_renders_golden_data_until_w3a_lands():
    html = _html()
    # The dashboard reads the manifest, attempts the hooked report path only
    # when declared, and says plainly which source the list shows.
    assert 'loadJSON("sample/manifest.json")' in html
    assert "loadOptional(ingestPath)" in html
    assert 'id="ingest-note"' in html
    assert "renderIngestNote(" in html
    assert "is not wired yet" in html
