"""Pipeline tests: acoustic-absence honesty, present-path detection, artifact shape.

Detector convention under test (see pipeline.py's module docstring): with no
G2 acoustic spans, raw ``detect()`` returns [] for D7 (indistinguishable from
zero), INFLATED gaps for D8, and FALSE FIRES for D6 -- so the report must
exclude 6/7/8 and label them ABSENT. These tests pin that behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

from turnstile_detectors import detect
from turnstile_pricing import price_trace
from turnstile_schema import Baselines, load_rates
from turnstile_verdict import adjudicate
from turnstile_ingest import describe_coverage, load, parse_call, run_call, run_calls

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate({"per_intent": {
    "order_status": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
    "refund": {"p50_turns": 8.0, "p75_turns": 10.5, "mean_cost_per_turn": 0.0029},
}})


def _absent_call():
    """TTS text with NO acoustic fields + a 3.3s mid-turn gap: raw D6 fires
    (unvoiced compose) and raw D8 fires (gap), so exclusion is load-bearing."""
    return {
        "id": "absent-001",
        "scenario": "order_status",
        "started": "2026-09-04T09:00:00Z",
        "ended": "2026-09-04T09:01:00Z",
        "end_reason": "caller_hangup",
        "telephony": {"provider": "twilio", "direction": "inbound", "billable_seconds": 60},
        "turns": [
            {
                "start_ms": 0, "end_ms": 8000,
                "asr": {"transcript": "Where is my order?", "start_ms": 200, "duration_ms": 1200},
                "llm": {"model": "gpt-5-mini", "input_tokens": 700, "output_tokens": 20,
                        "decision_kind": "compose", "decision": "report_status",
                        "output_text": "Your order ships tomorrow, arriving Thursday.",
                        "start_ms": 2000, "duration_ms": 600},
                "tts": {"text": "Your order ships tomorrow, arriving Thursday.",
                        "start_ms": 2700, "duration_ms": 2000},
            }
        ],
    }


def _present_call():
    """TTS WITH G2 counts, synthesized (200) > played (60): D7 must fire."""
    return {
        "id": "present-001",
        "scenario": "refund",
        "started": "2026-09-04T09:00:00Z",
        "ended": "2026-09-04T09:01:00Z",
        "end_reason": "caller_hangup",
        "telephony": {"provider": "twilio", "direction": "inbound", "billable_seconds": 60},
        "turns": [
            {
                "start_ms": 0, "end_ms": 9000, "speaker_first": "agent", "barge_in": True,
                "llm": {"model": "gpt-5-mini", "input_tokens": 900, "output_tokens": 40,
                        "decision_kind": "compose", "decision": "long_explanation",
                        "output_text": "Here is the full refund policy in detail for your review.",
                        "start_ms": 0, "duration_ms": 700},
                "tools": [{"name": "process_refund", "kind": "mutation", "effect": "committed",
                           "args": {"order_id": "ORD-1", "amount_usd": 10.0},
                           "start_ms": 800, "duration_ms": 500}],
                "tts": {"text": "Here is the full refund policy in detail for your review.",
                        "start_ms": 1400, "duration_ms": 5600,
                        "chars_synthesized": 200, "chars_played": 60},
            }
        ],
    }


def test_describe_coverage_marks_acoustic_classes_absent():
    coverage = describe_coverage(parse_call(_absent_call()))
    assert len(coverage) == 10
    for class_id in (6, 7, 8):
        assert coverage[class_id]["status"] == "absent"


def test_absence_full_pipeline_runs_and_labels_d6_d7_d8_absent():
    report = run_call(_absent_call(), RATES, BASELINES)
    assert report["verdict"]["label"] == "RESOLVED"
    for class_id in ("6", "7", "8"):
        entry = report["coverage"][class_id]
        assert entry["status"] == "absent"
        assert "no data for this input" in entry["reason"]
    for class_id in ("1", "2", "3", "4", "5", "9", "10"):
        assert report["coverage"][class_id]["status"] == "present"
    assert {f["class_id"] for f in report["findings"]} <= {1, 2, 3, 4, 5, 9, 10}


def test_absence_excludes_real_raw_findings_instead_of_zeroing():
    """The exclusion does work, not vacuous: raw detect() DOES fire D6/D8
    here, and the report drops those classes (never a faked zero)."""
    call = parse_call(_absent_call())
    priced = price_trace(load(call, rates=RATES), RATES)
    raw_classes = {f.class_id for f in detect(priced, adjudicate(priced), BASELINES)}
    assert 6 in raw_classes and 8 in raw_classes
    report = run_call(call, RATES, BASELINES)
    assert 6 in report["excluded_absent_classes"] and 8 in report["excluded_absent_classes"]
    assert not any(f["class_id"] in (6, 7, 8) for f in report["findings"])


def test_present_acoustics_run_d7_and_price_tts():
    report = run_call(_present_call(), RATES, BASELINES)
    for class_id in ("6", "7", "8"):
        assert report["coverage"][class_id]["status"] == "present"
    d7 = [f for f in report["findings"] if f["class_id"] == 7]
    assert len(d7) == 1
    assert d7[0]["evidence"]["wasted_chars"] == 140
    assert report["stage_costs_usd"]["tts"] > 0


def test_missing_telephony_marks_d8_absent():
    obj = _present_call()
    obj["telephony"] = None
    report = run_call(obj, RATES, BASELINES)
    assert report["coverage"]["8"]["status"] == "absent"
    assert report["coverage"]["7"]["status"] == "present"


def test_run_calls_artifact_shape_matches_dashboard_contract():
    artifact, details = run_calls(
        [_absent_call(), _present_call()], RATES, BASELINES,
        label="test", sample=False,
    )
    # Dashboard report envelope (manifest INGEST_CONTRACT).
    assert isinstance(artifact["label"], str)
    assert artifact["n"] == 2
    assert isinstance(artifact["note"], str)
    assert isinstance(artifact["provenance"], str)
    for key in ("n_conversations", "n_resolved", "total_cost_usd", "resolved_cost_usd",
                "cprc_loaded", "cprc_naive", "recoverable_margin_pct",
                "stage_costs_usd", "_provenance"):
        assert key in artifact["fleet"], key
    assert artifact["fleet"]["n_conversations"] == 2
    assert artifact["coverage_summary"]["n_calls"] == 2
    # Calls index rows shaped like the dashboard's own calls.json.
    assert len(artifact["calls"]) == 2
    for row in artifact["calls"]:
        assert set(row) == {"id", "scenario_id", "cost_usd", "verdict",
                            "end_reason", "n_turns", "top_waste", "detail"}
        detail = details[row["detail"]]
        assert set(detail) == {"trace", "span_costs", "turn_costs", "conv_cost",
                               "stage_costs", "verdict", "findings", "top_waste_usd",
                               "_provenance"}
        assert detail["conv_cost"] == row["cost_usd"]
        assert detail["trace"]["conversation"]["conversation_id"] == row["id"]
    for finding in artifact["findings"]:
        assert "call_id" in finding


def test_committed_data_artifact_is_dashboard_readable():
    data_dir = ROOT / "packages" / "ingest" / "data"
    path = data_dir / "data.json"
    assert path.exists(), "regenerate with: uv run python -m turnstile_ingest --sample"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["sample"] is True
    assert artifact["n"] == artifact["fleet"]["n_conversations"] >= 5
    assert artifact["n"] == artifact["coverage_summary"]["n_calls"]
    for row in artifact["calls"]:
        assert set(row) == {"id", "scenario_id", "cost_usd", "verdict",
                            "end_reason", "n_turns", "top_waste", "detail"}
        detail_path = data_dir / row["detail"]
        assert detail_path.exists(), f"missing per-call file {row['detail']}"
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        assert detail["conv_cost"] == row["cost_usd"]
        coverage = detail["_provenance"]["coverage"]
        assert len(coverage) == 10
        # The dashboard's acoustic rule: no G2 fields -> no D6/D7/D8 findings.
        assert "no data for this input" in coverage["8"]["reason"]
        assert not any(f["class_id"] in (6, 7, 8) for f in detail["findings"])
