import json, pytest
from pydantic import ValidationError
from turnstile_schema import Trace, load_trace

MINIMAL = {
    "conversation": {
        "conversation_id": "c1", "agent_version": "v1", "scenario_id": "order_status",
        "started_at": "2026-08-30T00:00:00Z", "ended_at": "2026-08-30T00:00:30Z",
        "end_reason": "caller_hangup"},
    "turns": [{
        "turn_index": 0, "speaker_first": "caller",
        "wall_start_ms": 0, "wall_end_ms": 3000,
        "llm": [{
            "span_id": "l0",
            "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 300,
            "gen_ai.system": "openai", "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 500, "gen_ai.usage.output_tokens": 20,
            "turnstile.decision_kind": "compose", "turnstile.decision_chosen": "greet",
            "turnstile.decision_candidates": ["greet"], "turnstile.output_text": "hello",
            "turnstile.latency_ms": 300}]}],
    "telephony": {
        "span_id": "leg1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 30000,
        "turnstile.provider": "twilio",
        "turnstile.direction": "inbound", "turnstile.billable_seconds": 30},
}

def test_trace_round_trips():
    t = Trace.model_validate(MINIMAL)
    assert t.turns[0].llm[0].decision_kind.value == "compose"
    assert t.telephony.billable_seconds == 30

def test_trace_rejects_unknown_top_level_key():
    bad = dict(MINIMAL, surprise=1)
    with pytest.raises(ValidationError):
        Trace.model_validate(bad)

def test_load_trace_from_disk(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(MINIMAL))
    assert load_trace(p).conversation.scenario_id == "order_status"
