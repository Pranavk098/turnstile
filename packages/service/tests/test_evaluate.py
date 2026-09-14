"""POST /api/evaluate: live engine runs, loud errors, parity, determinism.

P2 verify: (a) the INGEST.md example -> a report with a known finding,
(b) a misspelled field -> 422 with the path, (c) oversized body -> 413,
(d) the posted example yields the SAME report as the CLI on the same input.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient
from turnstile_schema import Baselines, load_rates
from turnstile_ingest.adapter import DEFAULT_RATES_PATH
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, run_calls

from turnstile_service.app import MAX_BODY_BYTES, MAX_CALLS, app

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[3]


def _rates_baselines():
    rates = load_rates(DEFAULT_RATES_PATH)
    baselines = Baselines.model_validate(
        json.loads(Path(DEFAULT_BASELINES_PATH).read_text(encoding="utf-8")))
    return rates, baselines


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    return json.loads(fence)


def _d7_variant() -> dict:
    """The doc example plus measured G2 char counts (synthesized > played):
    raw D7 fires and the envelope keeps it (coverage PRESENT)."""
    call = copy.deepcopy(_doc_example())
    call["id"] = "call-d7-demo-001"
    tts = call["turns"][0]["tts"]
    tts["chars_synthesized"] = 200
    tts["chars_played"] = 60
    return call


def test_evaluate_doc_example_returns_resolved_report():
    res = client.post("/api/evaluate", json=_doc_example())
    assert res.status_code == 200
    body = res.json()
    assert body["n"] == 1
    row = body["calls"][0]
    assert row["id"] == "call-20260904-001"
    assert row["verdict"] == "RESOLVED"
    assert body["fleet"]["n_conversations"] == 1
    # Honesty labels survive to the wire.
    assert body["provenance"] and body["fleet"]["_provenance"]["note"]
    assert body["coverage_summary"]["n_calls"] == 1


def test_evaluate_known_finding_is_d7_barge_in():
    res = client.post("/api/evaluate", json=_d7_variant())
    assert res.status_code == 200
    d7 = [f for f in res.json()["findings"] if f["class_id"] == 7]
    assert len(d7) == 1
    assert d7[0]["evidence"]["wasted_chars"] == 140
    assert d7[0]["call_id"] == "call-d7-demo-001"


def test_evaluate_misspelled_field_is_422_with_path():
    bad = _doc_example()
    bad["turns"][0]["llm"]["input_tokkens"] = bad["turns"][0]["llm"].pop("input_tokens")
    res = client.post("/api/evaluate", json=bad)
    assert res.status_code == 422
    assert "turns[0].llm.input_tokens" in res.json()["detail"]


def test_evaluate_garbage_shape_is_422_not_500():
    assert client.post("/api/evaluate", json={"foo": 1}).status_code == 422
    assert client.post("/api/evaluate", json=[]).status_code == 422
    res = client.post("/api/evaluate", content=b"{not json",
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 422


def test_evaluate_oversized_body_is_413():
    big = {"calls": [_doc_example()], "pad": "x" * (MAX_BODY_BYTES + 1)}
    res = client.post("/api/evaluate", json=big)
    assert res.status_code == 413


def test_evaluate_too_many_calls_is_413_without_engine_run():
    call = _doc_example()
    calls = []
    for i in range(MAX_CALLS + 1):
        dup = copy.deepcopy(call)
        dup["id"] = f"call-flood-{i:03d}"
        calls.append(dup)
    res = client.post("/api/evaluate", json={"calls": calls})
    assert res.status_code == 413


def test_evaluate_callset_and_bare_list_shapes():
    call = _doc_example()
    for payload in ({"calls": [call]}, [call]):
        res = client.post("/api/evaluate", json=payload)
        assert res.status_code == 200
        assert res.json()["n"] == 1


def test_evaluate_matches_cli_run_calls_exactly():
    """Parity: the service must not drift from the engine. The artifact
    portion of the POST body equals run_calls key-for-key (CLI byte-for-byte),
    and the additive `details` key equals run_calls' own detail payloads."""
    call = _d7_variant()
    rates, baselines = _rates_baselines()
    artifact, details = run_calls([call], rates, baselines,
                                  label="api evaluate (1 call(s))", sample=False)
    res = client.post("/api/evaluate", json=call)
    assert res.status_code == 200
    body = res.json()
    artifact_part = {k: v for k, v in body.items() if k != "details"}
    assert artifact_part == json.loads(json.dumps(artifact))
    assert body["details"] == json.loads(json.dumps(details))
    row = artifact["calls"][0]
    assert set(body["details"]) == {row["detail"]}
    assert body["details"][row["detail"]]["trace"]["conversation"][
        "conversation_id"] == row["id"]


def test_evaluate_is_deterministic():
    call = _d7_variant()
    first = client.post("/api/evaluate", json=call).content
    second = client.post("/api/evaluate", json=call).content
    assert first == second


def test_evaluate_provenance_retained_on_findings():
    res = client.post("/api/evaluate", json=_d7_variant())
    body = res.json()
    assert all("call_id" in f for f in body["findings"])
    assert body["fleet"]["stage_costs_usd"]["tts"] > 0


def test_evaluate_quality_beside_cost_to_the_wire():
    """PRD 04 §4.3 over HTTP: per-call detail and fleet aggregate both carry
    the quality block with tiers intact."""
    res = client.post("/api/evaluate", json=_d7_variant())
    body = res.json()
    detail = body["details"][body["calls"][0]["detail"]]
    quality = detail["quality"]
    assert quality["overall"] == {"label": "pass", "tier": "measured"}
    assert {d["id"] for d in quality["dimensions"]} >= {
        "task_success", "faithfulness", "answer_relevance"}
    tiers = {d["tier"] for d in quality["dimensions"]}
    assert tiers <= {"measured", "instrumented", "not_measured"}
    fleet_quality = body["fleet"]["quality"]
    assert fleet_quality["n_calls"] == 1
    assert fleet_quality["overall"] == {"pass": 1}


def test_evaluate_details_carry_provenance_and_coverage():
    res = client.post("/api/evaluate", json=_d7_variant())
    body = res.json()
    row = body["calls"][0]
    detail = body["details"][row["detail"]]
    assert set(detail) == {"trace", "span_costs", "turn_costs", "conv_cost",
                           "stage_costs", "verdict", "quality", "findings",
                           "top_waste_usd", "_provenance"}
    assert detail["_provenance"]["note"]
    assert detail["_provenance"]["coverage"]["7"]["status"] == "present"
    assert detail["conv_cost"] == row["cost_usd"]


def test_evaluate_detail_matches_dashboard_detail_contract():
    """Everything renderFlame/renderCallMeta read must be present, so the
    eval drill-down renders with the existing code path, not a copy."""
    res = client.post("/api/evaluate", json=_d7_variant())
    detail = res.json()["details"][res.json()["calls"][0]["detail"]]
    conv = detail["trace"]["conversation"]
    for key in ("scenario_id", "conversation_id", "end_reason"):
        assert conv[key], key
    turn = detail["trace"]["turns"][0]
    for key in ("turn_index", "speaker_first", "wall_start_ms", "wall_end_ms"):
        assert key in turn, key
    assert detail["verdict"]["label"]
    assert isinstance(detail["span_costs"], dict)
    assert isinstance(detail["stage_costs"], dict)
    assert isinstance(detail["turn_costs"], list)


def test_evaluate_early_413_without_engine_run(monkeypatch):
    """A declared Content-Length over the cap is rejected before the body is
    buffered and without touching the engine."""
    import sys

    # NB: `turnstile_service.app` as an attribute is the FastAPI instance
    # (re-exported by __init__); the module itself lives in sys.modules.
    app_module = sys.modules["turnstile_service.app"]

    def _boom(*args, **kwargs):
        raise AssertionError("engine must not run on an oversized body")

    monkeypatch.setattr(app_module, "run_calls", _boom)
    big = {"calls": [_doc_example()], "pad": "x" * (MAX_BODY_BYTES + 1)}
    res = client.post("/api/evaluate", json=big)
    assert res.status_code == 413
    assert str(MAX_BODY_BYTES) in res.json()["detail"]


def test_content_length_gate_edge_cases():
    from turnstile_service.app import _content_length_exceeds

    assert _content_length_exceeds({"content-length": str(MAX_BODY_BYTES + 1)}) is True
    assert _content_length_exceeds({"content-length": str(MAX_BODY_BYTES)}) is False
    assert _content_length_exceeds({}) is False
    assert _content_length_exceeds({"content-length": "not-a-number"}) is False
    assert _content_length_exceeds({"content-length": "-5"}) is False

def test_evaluate_cache_hit_skips_engine_byte_identical(monkeypatch):
    """P1 verify: a repeat POST of an identical call is served from cache --
    byte-identical to the cold response, with no second engine run."""
    import sys

    import turnstile_ingest.pipeline as pipeline

    app_module = sys.modules["turnstile_service.app"]
    calls = {"count": 0}
    real_run_calls = pipeline.run_calls

    def _counting(*args, **kwargs):
        calls["count"] += 1
        return real_run_calls(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_calls", _counting)
    call = _doc_example()
    call["id"] = "call-cache-spy-001"  # unique: no earlier test may have cached it
    first = client.post("/api/evaluate", json=call)
    assert first.status_code == 200
    second = client.post("/api/evaluate", json=call)
    assert second.status_code == 200
    assert calls["count"] == 1
    assert second.content == first.content
