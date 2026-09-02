"""Unit tests for the registry-driven verdict labels (Section C2, GAP-11):
PARTIALLY_RESOLVED and MISROUTED, emitted via the minimal scenario registry
(turnstile_verdict.registry). No golden fixture is modified here; fixture
updates are the owner's lane (see the branch's flagged-fixture note)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from turnstile_schema import PricedTrace
from turnstile_schema.enums import Effect, EndReason, ToolKind, ToolStatus, VerdictLabel
from turnstile_schema.spans import LlmDecide, ToolCall
from turnstile_schema.trace import Conversation, Trace, Turn
from turnstile_verdict import SCENARIO_REGISTRY, adjudicate
from turnstile_verdict.adjudicate import (
    CONF_PARTIALLY_RESOLVED,
    CONF_MISROUTED,
)


def _priced(trace: Trace) -> PricedTrace:
    span_ids: list[str] = []
    for turn in trace.turns:
        for group in (turn.vad, turn.asr, turn.llm, turn.tools, turn.tts, turn.playback):
            span_ids.extend(s.span_id for s in group)
        if turn.context is not None:
            span_ids.append(turn.context.span_id)
    return PricedTrace(
        trace=trace,
        span_costs={sid: 0.0 for sid in span_ids},
        turn_costs=[0.0] * len(trace.turns),
        conv_cost=0.0,
        stage_costs={"asr": 0.0, "llm": 0.0, "tts": 0.0, "telephony": 0.0},
    )


def _tool(name: str, kind: ToolKind, effect: Effect,
          status: ToolStatus = ToolStatus.ok) -> ToolCall:
    return ToolCall(
        span_id="tool1", start_offset_ms=0, duration_ms=100,
        tool_name=name, args_hash="sha256:a", args_json="{}",
        result_hash="sha256:b", latency_ms=100,
        tool_kind=kind, tool_status=status, effect=effect,
    )


def _synthetic(scenario_id: str, tool: ToolCall, llm_text: str = "I'm on it.") -> PricedTrace:
    turn = Turn(
        turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=1000,
        llm=[LlmDecide(
            span_id="llm1", start_offset_ms=0, duration_ms=100,
            gen_ai_system="openai", gen_ai_request_model="gpt-5",
            input_tokens=10, output_tokens=10,
            decision_kind="compose", decision_chosen="x", decision_candidates=["x"],
            output_text=llm_text, latency_ms=100,
        )],
        tools=[tool],
    )
    trace = Trace(
        conversation=Conversation(
            conversation_id="c1", agent_version="v1", scenario_id=scenario_id,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            end_reason=EndReason.caller_hangup,
        ),
        turns=[turn],
    )
    return _priced(trace)


def test_registry_covers_the_corpus_and_fixture_scenarios():
    assert set(SCENARIO_REGISTRY) == {
        "refund", "billing_dispute", "cancel_subscription", "appointment_reschedule",
        "account_update", "order_status", "tech_support", "balance_check",
        "long_technical_support",
    }
    assert SCENARIO_REGISTRY["refund"].requires_mutation == "process_refund"
    assert SCENARIO_REGISTRY["order_status"].requires_mutation is None


# -- MISROUTED ---------------------------------------------------------------- #

def test_committed_wrong_tool_mutation_is_misrouted():
    # Fixture 12's shape: a refund call whose committed mutation is an
    # account update -- the handled intent is not the scenario's intent.
    v = adjudicate(_synthetic("refund", _tool("update_address", ToolKind.mutation, Effect.committed)))
    assert v.label is VerdictLabel.MISROUTED
    assert v.confidence == pytest.approx(CONF_MISROUTED)
    ev = v.evidence[0]
    assert ev["rule"] == "handled_intent_mismatches_scenario"
    assert ev["handled_tool"] == "update_address"
    assert ev["required_tool"] == "process_refund"


def test_committed_mutation_on_a_lookup_scenario_is_misrouted():
    # order_status requires NO mutation: a committed mutation of ANY kind is
    # already a different intent than the one the caller asked for.
    v = adjudicate(_synthetic("order_status", _tool("update_address", ToolKind.mutation, Effect.committed)))
    assert v.label is VerdictLabel.MISROUTED
    assert v.evidence[0]["required_tool"] is None
    assert v.evidence[0]["handled_tool"] == "update_address"


def test_committed_required_tool_mutation_still_resolves():
    v = adjudicate(_synthetic("refund", _tool("process_refund", ToolKind.mutation, Effect.committed)))
    assert v.label is VerdictLabel.RESOLVED


def test_unregistered_scenario_keeps_pre_registry_behavior():
    # No registry entry -> no claim either way: committed mutation resolves
    # exactly as before the registry existed.
    v = adjudicate(_synthetic("mystery_scenario", _tool("whatever_tool", ToolKind.mutation, Effect.committed)))
    assert v.label is VerdictLabel.RESOLVED


# -- PARTIALLY_RESOLVED -------------------------------------------------------- #

def test_pending_required_mutation_is_partially_resolved():
    v = adjudicate(_synthetic("refund", _tool("process_refund", ToolKind.mutation, Effect.pending)))
    assert v.label is VerdictLabel.PARTIALLY_RESOLVED
    assert v.confidence == pytest.approx(CONF_PARTIALLY_RESOLVED)
    ev = v.evidence[0]
    assert ev["rule"] == "required_mutation_attempted_not_committed"


def test_pending_wrong_tool_mutation_is_not_partially_resolved():
    # "Partially" requires the attempt to be the scenario's own intent.
    v = adjudicate(_synthetic("refund", _tool("update_address", ToolKind.mutation, Effect.pending)))
    assert v.label is VerdictLabel.UNRESOLVED


def test_pending_unregistered_scenario_stays_unresolved():
    v = adjudicate(_synthetic("mystery_scenario", _tool("whatever_tool", ToolKind.mutation, Effect.pending)))
    assert v.label is VerdictLabel.UNRESOLVED


def test_pending_mutation_with_completion_claim_is_still_false_resolve():
    # The FALSE_RESOLVE check (Section B3's binding) still wins over the
    # partial label: a claim of completion contradicts the pending effect.
    v = adjudicate(_synthetic("refund", _tool("process_refund", ToolKind.mutation, Effect.pending),
                              llm_text="Your refund is processed."))
    assert v.label is VerdictLabel.FALSE_RESOLVE


def test_rejected_required_mutation_is_unresolved_not_partially_resolved():
    # A rejected attempt is a failure, not a partial success.
    v = adjudicate(_synthetic("refund", _tool("process_refund", ToolKind.mutation, Effect.rejected)))
    assert v.label is VerdictLabel.UNRESOLVED