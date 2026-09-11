"""Function-calling policy tests (TDD -- written FIRST, red).

A fake OpenAI client stands in (no network): tool calls, content replies,
and empty replies are all exercised. The commit path is proven at the
harness level -- a mock FC policy selecting the required tool must be able
to reach rule1 True (the outcome Phase 3 could never produce).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates

from turnstile_live.openloop import SCRIPT_SET, run_live
from turnstile_live.voice import FunctionCallingPolicy, LlmDecision, function_schemas_for

RATES = load_rates(Path(__file__).parents[3] / "pricing" / "rates.yaml")


class _FakeFunction:
    def __init__(self, name: str, arguments: str = "{}") -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, function) -> None:
        self.function = function
        self.id = "call-1"
        self.type = "function"


class _FakeMessage:
    def __init__(self, content, tool_calls) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message) -> None:
        self.message = message


class _FakeUsage:
    def __init__(self) -> None:
        self.prompt_tokens = 120
        self.completion_tokens = 30


class _FakeResponse:
    def __init__(self, content, tool_calls) -> None:
        self.choices = [_FakeChoice(_FakeMessage(content, tool_calls))]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, response) -> None:
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeChat:
    def __init__(self, completions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, response) -> None:
        self.completions = _FakeCompletions(response)
        self.chat = _FakeChat(self.completions)


def _policy(response, monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    return FunctionCallingPolicy(client=_FakeClient(response))


# --------------------------------------------------------------------------- #
# Schemas: the scenario's tools, required terminal tool included.              #
# --------------------------------------------------------------------------- #

def test_schemas_include_the_required_tool():
    names = [t["function"]["name"] for t in function_schemas_for("refund")]
    assert "process_refund" in names
    assert "lookup_account" in names


def test_lookup_scenario_has_no_mutation_tool():
    names = [t["function"]["name"] for t in function_schemas_for("order_status")]
    assert "lookup_account" in names
    assert "process_refund" not in names


def test_schemas_are_valid_function_defs():
    for schema in function_schemas_for("billing_dispute"):
        assert schema["type"] == "function"
        assert schema["function"]["name"]
        assert "parameters" in schema["function"]


# --------------------------------------------------------------------------- #
# Decisions: tool calls, content replies, empty replies, gate.                 #
# --------------------------------------------------------------------------- #

def test_tool_call_selects_the_function(monkeypatch):
    response = _FakeResponse(
        "I'll process that refund now.",
        [_FakeToolCall(_FakeFunction("process_refund", '{"order_id": "ORD-1"}'))],
    )
    decision = _policy(response, monkeypatch).decide("refund", "I want a refund.", 1, None)
    assert (decision.decision_kind, decision.decision) == ("tool_select", "process_refund")
    assert decision.reply == "I'll process that refund now."
    assert (decision.input_tokens, decision.output_tokens) == (120, 30)
    assert decision.fallback is False


def test_tool_call_with_empty_content_records_empty_reply(monkeypatch):
    """The model acted without speaking -- output_text "" is the TRUE record
    (never a fabricated utterance)."""
    response = _FakeResponse(None, [_FakeToolCall(_FakeFunction("process_refund"))])
    decision = _policy(response, monkeypatch).decide("refund", "I want a refund.", 1, None)
    assert (decision.decision_kind, decision.decision) == ("tool_select", "process_refund")
    assert decision.reply == ""


def test_content_reply_without_tool_call_parses_the_label(monkeypatch):
    response = _FakeResponse("Routing you to billing_dispute now.", None)
    decision = _policy(response, monkeypatch).decide("billing_dispute", "My bill.", 0, None)
    assert decision.decision == "billing_dispute"
    assert decision.fallback is False


def test_content_without_any_label_falls_back_to_mock(monkeypatch):
    response = _FakeResponse("Hello there, how can I help?", None)
    decision = _policy(response, monkeypatch).decide("refund", "Hello?", 0, None)
    assert decision.fallback is True
    assert decision.reply


def test_policy_refuses_without_the_paid_gate(monkeypatch):
    monkeypatch.delenv("TURNSTILE_ALLOW_PAID", raising=False)
    with pytest.raises(RuntimeError, match="TURNSTILE_ALLOW_PAID"):
        FunctionCallingPolicy(client=_FakeClient(_FakeResponse("x", None)))


def test_tools_are_sent_on_the_request(monkeypatch):
    response = _FakeResponse("ok billing_dispute", None)
    client = _FakeClient(response)
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    FunctionCallingPolicy(client=client).decide("billing_dispute", "My bill.", 0, None)
    sent = client.completions.calls[0]
    assert "tools" in sent
    assert any(t["function"]["name"] == "adjust_billing" for t in sent["tools"])


# --------------------------------------------------------------------------- #
# Commit path: required tool selected -> rule1 CAN go True.                    #
# --------------------------------------------------------------------------- #

class MockFcPolicy:
    """Canned function-calling-style decisions: runs the required tool on
    turn 1, closes on turn 2."""

    def __init__(self, required_tool: str) -> None:
        self._required_tool = required_tool

    def decide(self, scenario, transcript, turn_index, candidates=None):
        if turn_index == 0:
            return LlmDecision("route", scenario, "Looking into it.", 700, 20, False, 0.0)
        if turn_index == 1:
            return LlmDecision("tool_select", self._required_tool,
                               "Running it now.", 700, 20, False, 0.0)
        return LlmDecision("compose", "close_call",
                           "Glad I could help — anything else today?", 700, 20, False, 0.0)


def test_required_tool_commit_can_reach_rule1_true():
    from turnstile_live.openloop import rule1_registry

    conv = next(c for c in SCRIPT_SET if c.scenario == "refund")
    live, _call = run_live(conv, MockFcPolicy("process_refund"), RATES)
    tools = [(n, e) for t in live.turns for n, e in t.tools]
    assert ("process_refund", "committed") in tools
    assert live.verdict_label == "RESOLVED"
    assert rule1_registry("refund", tools, live.verdict_label) is True
