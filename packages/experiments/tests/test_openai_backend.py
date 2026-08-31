"""Tests for OpenAIBackend (packages/experiments) -- GATED HARD, and tested
with a MOCKED openai client only. Nothing in this file makes a real network
call: TURNSTILE_ALLOW_PAID / OPENAI_API_KEY are set to inert test values, and
a hand-written fake client stands in for `openai.OpenAI` throughout."""
from __future__ import annotations

import pytest

from turnstile_schema import VariantSpec
from turnstile_schema.enums import DecisionKind
from turnstile_replay.backend import ReplayContext

from turnstile_experiments.openai_backend import OpenAIBackend

from _experiments_builders import asr, llm, turn


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeCompletions:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.completions = _FakeCompletions(response)
        self.chat = _FakeChat(self.completions)


# --------------------------------------------------------------------------- #
# Gating -- both env vars required, regardless of injected client.            #
# --------------------------------------------------------------------------- #

def test_raises_without_allow_paid_flag(monkeypatch):
    monkeypatch.delenv("TURNSTILE_ALLOW_PAID", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    with pytest.raises(RuntimeError, match="TURNSTILE_ALLOW_PAID"):
        OpenAIBackend(client=_FakeClient(_FakeResponse("x", 1, 1)))


def test_raises_without_api_key(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIBackend(client=_FakeClient(_FakeResponse("x", 1, 1)))


def test_raises_even_with_client_injected_if_flag_missing(monkeypatch):
    """The gate is about authorizing spend, not about being able to
    construct a client -- injecting a client must not bypass it."""
    monkeypatch.delenv("TURNSTILE_ALLOW_PAID", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    with pytest.raises(RuntimeError):
        OpenAIBackend(client=_FakeClient(_FakeResponse("x", 1, 1)))


# --------------------------------------------------------------------------- #
# Request formation + response parsing, with both env vars set to inert test  #
# values and a fake client (never touches the network).                      #
# --------------------------------------------------------------------------- #

def test_forms_correct_request_and_parses_response(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    fake_client = _FakeClient(_FakeResponse("hello there", prompt_tokens=42, completion_tokens=7))
    backend = OpenAIBackend(client=fake_client)

    context = ReplayContext(
        conversation_id="c1", scenario_id="refund", turn_index=1,
        turns_before=(turn(0, asr_spans=[asr("a1", transcript="I need a refund")],
                            llm_spans=[llm("l0", output_text="Sure, let me check.")]),),
    )
    original_span = llm("l1", decision_kind=DecisionKind.route, model="gpt-5")
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})

    decision = backend(context, original_span, variant)

    # Correct model per variant's routing.
    assert len(fake_client.completions.calls) == 1
    call = fake_client.completions.calls[0]
    assert call["model"] == "gpt-5-nano"

    # Pinned context is present in the formed request.
    messages_text = " ".join(m["content"] for m in call["messages"])
    assert "I need a refund" in messages_text
    assert "Sure, let me check." in messages_text

    # Response correctly parsed into a ReplayedDecision.
    assert decision.model == "gpt-5-nano"
    assert decision.output_text == "hello there"
    assert decision.decision_chosen == "hello there"
    assert decision.input_tokens == 42
    assert decision.output_tokens == 7


def test_falls_back_to_original_model_when_variant_does_not_route_this_decision(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    fake_client = _FakeClient(_FakeResponse("ok", 1, 1))
    backend = OpenAIBackend(client=fake_client)

    context = ReplayContext(conversation_id="c1", scenario_id="refund", turn_index=0, turns_before=())
    original_span = llm("l1", decision_kind=DecisionKind.compose, model="gpt-5-mini")
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})  # doesn't touch "compose"

    decision = backend(context, original_span, variant)

    assert fake_client.completions.calls[0]["model"] == "gpt-5-mini"
    assert decision.model == "gpt-5-mini"


def test_no_model_routing_at_all_uses_original_model(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    fake_client = _FakeClient(_FakeResponse("ok", 1, 1))
    backend = OpenAIBackend(client=fake_client)

    context = ReplayContext(conversation_id="c1", scenario_id="refund", turn_index=0, turns_before=())
    original_span = llm("l1", decision_kind=DecisionKind.route, model="gpt-5")
    variant = VariantSpec(context_strategy="window:8")

    decision = backend(context, original_span, variant)

    assert fake_client.completions.calls[0]["model"] == "gpt-5"
    assert decision.model == "gpt-5"
