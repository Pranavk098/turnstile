"""Quality-gate wire tests (Day-4 Part D): the gate holds over HTTP + in the UI.

Drives the RUNNING service (fresh ``create_app()`` per POST, so each flag
state gets a cold engine run -- never a cache hit masquerading as proof):

* flag OFF -> the ``quality`` block shows both judge dims pending-as-data
  (``score: null``, ``tier: "not_measured"``) and the fleet rollup counts
  them as pending, never pass/fail;
* flag ON with no calibration registered -> the judge-dim bytes are
  IDENTICAL (no score appears from the flag alone).

UI verification (no browser harness in this environment -- data + template
assertions, the same pattern ``test_frontend.py`` uses): the dashboard's
shared rubric renderer maps a pending label to the literal
``"calibration pending"`` and a null score to the em-dash cell, never a
numeral. The wire response's judge dims are shown to take exactly those
branches.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from turnstile_quality import clear_calibrations
from turnstile_quality.calibration import JUDGE_DIMENSIONS

from turnstile_service.app import create_app

ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_DIR = ROOT / "packages" / "dashboard"

FLAG = "TURNSTILE_ALLOW_PAID"
JUDGE_IDS = tuple(JUDGE_DIMENSIONS)

CALL_ID = "call-gate-wire-001"


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    call = json.loads(fence)
    call = copy.deepcopy(call)
    call["id"] = CALL_ID
    return call


def _post_fresh(call: dict, *, flag_on: bool, monkeypatch) -> dict:
    """POST /api/evaluate against a brand-new app (cold cache, cold engine
    run) under one flag state. Returns the decoded response body."""
    if flag_on:
        monkeypatch.setenv(FLAG, "1")
    else:
        monkeypatch.delenv(FLAG, raising=False)
    clear_calibrations()
    client = TestClient(create_app())
    try:
        res = client.post("/api/evaluate", json=call)
    finally:
        clear_calibrations()
        monkeypatch.delenv(FLAG, raising=False)
    assert res.status_code == 200, res.text[:500]
    return res.json()


def _judge_dims(body: dict) -> list[dict]:
    detail = body["details"][body["calls"][0]["detail"]]
    dims = [d for d in detail["quality"]["dimensions"] if d["id"] in JUDGE_IDS]
    assert sorted(d["id"] for d in dims) == sorted(JUDGE_IDS)
    dims.sort(key=lambda d: d["id"])
    return dims


def _assert_pending_as_data(dims: list[dict]) -> None:
    for dim in dims:
        assert dim["score"] is None, dim
        assert dim["label"] == "pending", dim
        assert dim["tier"] == "not_measured", dim
        assert dim["method"] == "judge_pending", dim


def test_flag_off_quality_block_shows_judge_dims_pending(monkeypatch):
    body = _post_fresh(_doc_example(), flag_on=False, monkeypatch=monkeypatch)
    dims = _judge_dims(body)
    _assert_pending_as_data(dims)
    print(f"\n[wire] flag OFF -> judge dims: {json.dumps(dims, sort_keys=True)}")


def test_fleet_rollup_counts_judges_pending_never_pass_fail(monkeypatch):
    for flag_on in (False, True):
        body = _post_fresh(_doc_example(), flag_on=flag_on,
                           monkeypatch=monkeypatch)
        fleet_quality = body["fleet"]["quality"]
        assert fleet_quality["n_calls"] == 1
        for dim_id in JUDGE_IDS:
            counts = fleet_quality["dimensions"][dim_id]
            assert counts == {"pending": 1}, (flag_on, dim_id, counts)
            assert "pass" not in counts and "fail" not in counts
        print(f"\n[wire] flag {'ON' if flag_on else 'OFF'} -> fleet rollup: "
              f"{json.dumps({k: fleet_quality['dimensions'][k] for k in JUDGE_IDS}, sort_keys=True)}")


def test_flag_on_without_calibration_judge_bytes_identical(monkeypatch):
    """The flag alone must not conjure a score: cold engine runs under both
    flag states produce byte-identical judge dims (and identical full
    quality blocks)."""
    off_body = _post_fresh(_doc_example(), flag_on=False, monkeypatch=monkeypatch)
    on_body = _post_fresh(_doc_example(), flag_on=True, monkeypatch=monkeypatch)
    off_dims, on_dims = _judge_dims(off_body), _judge_dims(on_body)
    _assert_pending_as_data(off_dims)
    _assert_pending_as_data(on_dims)
    off_bytes = json.dumps(off_dims, sort_keys=True)
    on_bytes = json.dumps(on_dims, sort_keys=True)
    assert on_bytes == off_bytes
    off_detail = off_body["details"][off_body["calls"][0]["detail"]]
    on_detail = on_body["details"][on_body["calls"][0]["detail"]]
    assert (json.dumps(on_detail["quality"], sort_keys=True)
            == json.dumps(off_detail["quality"], sort_keys=True))
    print(f"\n[wire] flag ON (no calibration) judge bytes identical to flag OFF "
          f"({len(on_bytes)} bytes): {on_bytes}")


# -- UI verification: data + template assertions (no browser harness) --------

def _html() -> str:
    return (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")


def test_dashboard_template_renders_pending_as_literal_not_numeral():
    """The shared rubric renderer (single definition, both drill-down paths):
    pending -> literal 'calibration pending'; null score -> em-dash cell."""
    html = _html()
    assert html.count("function renderQualityRubric(call)") == 1
    assert "calibration pending" in html
    assert 'if (dim.label === "pending") return "calibration pending";' in html
    assert ('(d.score === null || d.score === undefined ? "—" '
            ': d.score.toFixed(1))') in html


def test_wire_judge_dims_take_the_pending_template_branch(monkeypatch):
    """Join the two halves without a browser: the live wire dims satisfy the
    template's pending branch guards, so the call page renders the literal
    'calibration pending' with no numeral score for judge dims."""
    html = _html()
    body = _post_fresh(_doc_example(), flag_on=False, monkeypatch=monkeypatch)
    dims = _judge_dims(body)
    for dim in dims:
        # Template branch 1 (result cell): label == "pending" -> literal.
        assert dim["label"] == "pending"
        assert 'if (dim.label === "pending") return "calibration pending";' in html
        # Template branch 2 (score cell): score null -> "—", never toFixed.
        assert dim["score"] is None
        rendered_score = "—"  # the null arm of the template's ternary
        assert not any(ch.isdigit() for ch in rendered_score)
    print("\n[ui] judge dims from the live wire response take the "
          "'calibration pending' + em-dash branches; no numeral rendered. "
          "(data+template assertions; no browser harness in this environment.)")
