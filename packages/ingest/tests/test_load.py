"""Adapter tests: sample round-trip, malformed-input errors, rate keys."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from turnstile_schema import Trace, load_rates
from turnstile_ingest import IngestError, load

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
SAMPLE = json.loads((ROOT / "packages" / "ingest" / "sample" / "calls.json").read_text())


def _minimal_call(**overrides):
    call = {
        "id": "test-001",
        "scenario": "order_status",
        "started": "2026-09-04T09:00:00Z",
        "ended": "2026-09-04T09:01:00Z",
        "end_reason": "caller_hangup",
        "telephony": {"provider": "twilio", "direction": "inbound", "billable_seconds": 60},
        "turns": [
            {
                "start_ms": 0, "end_ms": 5000,
                "asr": {"transcript": "Where is my order?", "start_ms": 200, "duration_ms": 1200},
                "llm": {"model": "gpt-5-mini", "input_tokens": 700, "output_tokens": 12,
                        "decision_kind": "compose", "decision": "report_status",
                        "output_text": "Your order ships tomorrow.", "start_ms": 1500, "duration_ms": 600},
                "tts": {"text": "Your order ships tomorrow.", "start_ms": 2200, "duration_ms": 1800},
            }
        ],
    }
    call.update(overrides)
    return call


def test_sample_round_trips_to_valid_traces():
    assert SAMPLE["sample"] is True
    assert len(SAMPLE["calls"]) >= 5
    for obj in SAMPLE["calls"]:
        trace = load(obj, rates=RATES)
        assert isinstance(trace, Trace)
        assert trace.conversation.conversation_id == obj["id"]
        assert trace.conversation.scenario_id == obj["scenario"]
        assert len(trace.turns) == len(obj["turns"])
        assert trace.telephony is not None


def test_missing_field_points_at_field():
    obj = _minimal_call()
    del obj["turns"][0]["llm"]["input_tokens"]
    with pytest.raises(IngestError) as excinfo:
        load(obj, rates=RATES)
    assert "turns[0].llm.input_tokens" in str(excinfo.value)


def test_bad_end_reason_points_at_field():
    obj = _minimal_call(end_reason="hungup")
    with pytest.raises(IngestError) as excinfo:
        load(obj, rates=RATES)
    assert "end_reason" in str(excinfo.value)


def test_empty_object_points_at_field():
    with pytest.raises(IngestError) as excinfo:
        load({}, rates=RATES)
    assert "id" in str(excinfo.value)


def test_inconsistent_tool_kind_effect_points_at_problem():
    obj = _minimal_call()
    obj["turns"][0]["tools"] = [
        {"name": "lookup_order", "kind": "lookup", "effect": "committed",
         "args": {"order_id": "ORD-1"}}
    ]
    with pytest.raises(IngestError) as excinfo:
        load(obj, rates=RATES)
    assert "effect" in str(excinfo.value)


def test_unknown_model_points_at_field_with_known_keys():
    obj = _minimal_call()
    obj["turns"][0]["llm"]["model"] = "acme-ultra"
    with pytest.raises(IngestError) as excinfo:
        load(obj, rates=RATES)
    message = str(excinfo.value)
    assert "turns[0].llm.model" in message
    assert "openai/acme-ultra" in message


def test_ingest_error_is_value_error():
    assert issubclass(IngestError, ValueError)
