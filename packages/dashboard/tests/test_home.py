"""W3-B Item 3 -- home.html is the product entry: what Turnstile is, the honest
tiers, and a clear path into the dashboard (including the call list).

The headline numbers are snapshots -- this pins them to the pipeline output
they claim, so a data regeneration that moves the numbers fails here instead
of silently lying on the landing page."""
from __future__ import annotations

import json

import build_data


def _home() -> str:
    return (build_data.DASHBOARD_DIR / "home.html").read_text(encoding="utf-8")


def _sample(name: str) -> dict:
    return json.loads(
        (build_data.DASHBOARD_DIR / "sample" / name).read_text(encoding="utf-8"))


def test_home_numbers_match_the_pipeline_output():
    home = _home()
    fleet = _sample("fleet.json")
    bargein = _sample("bargein.sample.json")
    conditional = _sample("conditional.sample.json")
    assert f"{fleet['recoverable_margin_pct']:.2f}<small>%</small>" in home
    assert f"{bargein['headline']['waste_share_of_tts_spend'] * 100:.1f}<small>%</small>" in home
    assert f"${conditional['total_savings_usd']:.5f}" in home


def test_home_paths_into_the_dashboard():
    home = _home()
    assert 'href="index.html"' in home
    assert 'href="index.html#calls"' in home
    assert "METHOD.md" in home
    # The dashboard fetches local JSON: the entry says how to serve it.
    assert "http.server" in home
