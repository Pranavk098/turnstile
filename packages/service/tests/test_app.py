"""Read endpoints: committed JSON served verbatim, provenance intact.

P1 verify: shapes + a provenance key on each; numbers equal the CLI's
data.json byte-for-byte for the same fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from turnstile_service.app import app
from turnstile_service.data import READ_ENDPOINTS

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DIR = ROOT / "packages" / "dashboard" / "sample"


def _sample(name: str) -> bytes:
    return (SAMPLE_DIR / name).read_bytes()


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["commit"], str) and body["commit"]


def test_sample_endpoints_serve_committed_bytes_verbatim():
    for name, filename in READ_ENDPOINTS.items():
        res = client.get(f"/api/{name}")
        assert res.status_code == 200, name
        assert res.content == _sample(filename), name


def test_fleet_shape_and_provenance():
    fleet = client.get("/api/fleet").json()
    for key in ("label", "note", "n_conversations", "n_resolved",
                "total_cost_usd", "resolved_cost_usd", "cprc_loaded",
                "cprc_naive", "recoverable_margin_pct", "stage_costs_usd",
                "_provenance"):
        assert key in fleet, key
    assert "MockBackend" in fleet["_provenance"]["note"]


def test_calls_index_lists_demo_call_ids():
    payload = client.get("/api/calls").json()
    assert payload["n"] == len(payload["calls"]) == 23
    ids = [row["id"] for row in payload["calls"]]
    assert "09_escalation_debt" in ids
    assert payload["hero"] == "09_escalation_debt"


def test_call_report_has_hero_finding_with_honesty_label():
    detail = client.get("/api/calls/07_barge_in_waste").json()
    assert detail["verdict"]["label"] in ("RESOLVED", "PARTIALLY_RESOLVED",
                                          "UNRESOLVED", "ESCALATED", "ABANDONED",
                                          "MISROUTED", "FALSE_RESOLVE")
    d7 = [f for f in detail["findings"] if f["class_id"] == 7]
    assert d7, "hero D7 barge-in finding must be served"
    assert d7[0]["waste_usd"] > 0
    assert "Barge-in waste" in (client.get("/").text)


def test_call_report_provenance_key_present():
    detail = client.get("/api/calls/09_escalation_debt").json()
    assert "_provenance" in detail and detail["_provenance"]["note"]


def test_unknown_call_is_404_not_500():
    assert client.get("/api/calls/no-such-call").status_code == 404


def test_path_traversal_is_404_not_a_file_read():
    assert client.get("/api/calls/..%2Fapp").status_code in (404, 422)
    assert client.get("/api/calls/%2E%2E%2Fsecret").status_code in (404, 422)


def test_ingest_report_equals_cli_artifact_byte_for_byte():
    cli_artifact = (ROOT / "packages" / "ingest" / "data" / "data.json").read_bytes()
    res = client.get("/api/ingest")
    assert res.status_code == 200
    assert res.content == cli_artifact
    body = json.loads(res.content)
    assert body["provenance"] and body["fleet"]["_provenance"]["note"]


def test_ingest_call_detail_served():
    artifact = json.loads((ROOT / "packages" / "ingest" / "data" / "data.json").read_text())
    row = artifact["calls"][0]
    res = client.get(f"/api/calls/{row['id']}")
    assert res.status_code == 200
    assert res.json()["conv_cost"] == row["cost_usd"]


def test_example_matches_docs_ingest_fence():
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    assert json.loads(fence) == client.get("/api/example").json()


def test_static_dashboard_still_served_same_origin():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    res = client.get("/sample/fleet.json")
    assert res.status_code == 200
    assert res.content == _sample("fleet.json")
