"""Small synthetic-trace builders shared by the replay test files (mirrors the
small per-file builder helpers in packages/pricing/tests, packages/verdict/tests
and packages/detectors/tests/_builders.py)."""
from __future__ import annotations

from datetime import datetime, timezone

from turnstile_schema import PricedTrace
from turnstile_schema.enums import DecisionKind, EndReason, ToolKind
from turnstile_schema.spans import LlmDecide, ToolCall
from turnstile_schema.trace import Conversation, Trace, Turn
from turnstile_pricing import price_trace

from turnstile_replay._rates import get_rates


def conv(end_reason: EndReason = EndReason.caller_hangup, scenario_id: str = "s1",
         conversation_id: str = "c1") -> Conversation:
    return Conversation(
        conversation_id=conversation_id, agent_version="v1", scenario_id=scenario_id,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        end_reason=end_reason,
    )


def llm(sid, *, start=0, dur=500, model="gpt-5", input_tokens=500, output_tokens=15,
        decision_kind=DecisionKind.route, decision_chosen="x", output_text="x",
        cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0,
        latency_ms=None) -> LlmDecide:
    return LlmDecide(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        gen_ai_system="openai", gen_ai_request_model=model,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        decision_kind=decision_kind, decision_chosen=decision_chosen,
        decision_candidates=[decision_chosen],
        output_text=output_text, latency_ms=latency_ms if latency_ms is not None else dur,
    )


def tool(sid, *, start=0, dur=300, name="do_thing", args_hash="sha256:a",
         kind=ToolKind.mutation, effect=None) -> ToolCall:
    return ToolCall(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        tool_name=name, args_hash=args_hash, args_json="{}", result_hash="sha256:r",
        latency_ms=dur, tool_kind=kind,
        effect=effect if effect is not None else (
            "committed" if kind in (ToolKind.mutation, ToolKind.handoff) else "none"
        ),
    )


def turn(idx, wall_start=0, wall_end=1000, *, llm_spans=(), tools=(),
         speaker_first="agent") -> Turn:
    return Turn(
        turn_index=idx, speaker_first=speaker_first, wall_start_ms=wall_start,
        wall_end_ms=wall_end, llm=list(llm_spans), tools=list(tools),
    )


def trace(*turns: Turn, end_reason: EndReason = EndReason.caller_hangup,
          conversation_id: str = "c1") -> Trace:
    return Trace(conversation=conv(end_reason=end_reason, conversation_id=conversation_id),
                 turns=list(turns))


def priced(*turns: Turn, end_reason: EndReason = EndReason.caller_hangup,
           conversation_id: str = "c1") -> PricedTrace:
    """Build+price a synthetic trace against the REAL pricing/rates.yaml (via
    replay's own get_rates(), the same file replay() re-prices replayed
    traces against), so a synthetic trace's original conv_cost and a
    replayed trace's conv_cost are computed from the same rate table."""
    return price_trace(
        trace(*turns, end_reason=end_reason, conversation_id=conversation_id),
        get_rates(),
    )
