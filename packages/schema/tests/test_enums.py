import pytest
from pydantic import ValidationError
from turnstile_schema.enums import EndReason, ToolStatus, Effect
from turnstile_schema.trace import Conversation

def test_end_reason_vocabulary():
    assert set(e.value for e in EndReason) == {
        "caller_hangup", "agent_hangup", "escalated", "timeout", "error"}

def test_conversation_rejects_unknown_end_reason():
    with pytest.raises(ValidationError):
        Conversation(
            conversation_id="c1", agent_version="v1", scenario_id="s1",
            started_at="2026-08-30T00:00:00Z", ended_at="2026-08-30T00:01:00Z",
            end_reason="exploded")

def test_conversation_defaults_schema_version():
    c = Conversation(
        conversation_id="c1", agent_version="v1", scenario_id="s1",
        started_at="2026-08-30T00:00:00Z", ended_at="2026-08-30T00:01:00Z",
        end_reason="caller_hangup")
    assert c.schema_version == "1.1"

def test_tool_status_vocabulary():
    assert set(e.value for e in ToolStatus) == {"ok", "error"}

def test_effect_vocabulary():
    assert set(e.value for e in Effect) == {
        "committed", "pending", "rejected", "none", "unknown"}
