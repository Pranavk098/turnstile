"""Front-end contract: the dashboard page and the service agree.

Pins what PRD 01 P3 promises without a browser: every /api/* alias the
page tries exists as a route, the textarea preset is byte-equal to the
docs/INGEST.md example, and the no-embedded-data rule still holds.
"""
from __future__ import annotations

import json
from pathlib import Path

from turnstile_service.app import app
from turnstile_service.data import READ_ENDPOINTS

ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_DIR = ROOT / "packages" / "dashboard"


def _html() -> str:
    return (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    return json.loads(fence)


def _js_object(name: str) -> dict:
    """Parse a top-level `const <name> = {...};` literal from the page."""
    html = _html()
    start = html.index(f"const {name} =") + len(f"const {name} =")
    depth, i, in_str, esc = 0, start, None, False
    while True:
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
        elif ch in ("'", '"'):
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:i + 1])
        i += 1


def test_every_api_alias_the_page_tries_exists_as_a_route():
    html = _html()
    paths = {route.path for route in app.routes}
    for filename, api in {
        "sample/manifest.json": "/api/manifest",
        "sample/bargein.sample.json": "/api/bargein",
        "sample/priced_trace.json": "/api/hero",
        "sample/fleet.json": "/api/fleet",
        "sample/findings.sample.json": "/api/findings",
        "sample/experiments.sample.json": "/api/experiments",
        "sample/conditional.sample.json": "/api/conditional",
        "sample/calls.json": "/api/calls",
        "sample/ingest.json": "/api/ingest",
    }.items():
        assert f'"{filename}": "{api}"' in html, filename
        assert api in paths, api
    assert "/api/calls/{call_id}" in paths
    assert "/api/evaluate" in paths
    assert "/api/example" in paths
    assert set(READ_ENDPOINTS) == {"manifest", "fleet", "calls", "hero",
                                   "findings", "experiments", "conditional",
                                   "bargein"}


def test_textarea_preset_is_the_docs_example_verbatim():
    assert _js_object("EVAL_DOC_EXAMPLE") == _doc_example()


def test_evaluate_panel_markup_and_states():
    html = _html()
    assert 'id="evaluate"' in html
    assert 'id="eval-input"' in html
    assert 'id="eval-run"' in html
    assert 'id="eval-status"' in html
    assert 'id="eval-results"' in html
    assert '"Doc example"' in html or ">Doc example<" in html
    assert "Barge-in demo" in html
    assert "chars_synthesized" in html  # D7 preset carries G2 counts
    assert "Computing" in html  # cold-start reads as working
    assert "No demo service here" in html  # honest file:// fallback
    assert "/api/evaluate" in html
    assert "runEval()" in html or "runEval" in html


def test_no_embedded_data_copies_introduced():
    html = _html()
    assert "application/json" not in html
    assert "data-bargein" not in html


def test_eval_drill_down_reuses_the_existing_detail_renderer():
    """No second renderer: pasted-eval rows open via renderFlame +
    renderCallMeta, fed from the response's `details` map."""
    html = _html()
    assert "lastEvalDetails = artifact.details || null" in html
    assert "function showEvalCall(filename)" in html
    assert "data-eval-detail" in html
    # Same calls as the dataset drill-down (routeCall), in the same order.
    body = html.split("function showEvalCall(filename)")[1].split("function initEvalPanel")[0]
    assert body.index("renderFlame(detail)") < body.index("renderCallMeta(detail)")
    # Existing renderer untouched: still the single definition each.
    assert html.count("function renderFlame(pt)") == 1
    assert html.count("function renderCallMeta(call)") == 1
    # Plain #hero fragment -- the #/call/ router is not claimed or altered.
    assert '<a href="#hero" data-eval-detail="' in html


def test_home_links_into_live_eval():
    home = (DASHBOARD_DIR / "home.html").read_text(encoding="utf-8")
    assert 'href="index.html#evaluate"' in home
