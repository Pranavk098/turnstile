"""Small synthetic-trace builders for packages/experiments tests (mirrors
packages/replay/tests/_replay_builders.py -- named distinctly to avoid the
same-basename pytest test-collection collision documented in
packages/replay's report)."""
from __future__ import annotations

from datetime import datetime, timezone

from turnstile_pricing import price_trace
from turnstile_schema import PricedTrace, load_rates
from turnstile_schema.enums import DecisionKind, EndReason, ToolKind
from turnstile_schema.spans import AsrTranscribe, LlmDecide, ToolCall
from turnstile_schema.trace import Conversation, Trace, Turn

RATES = load_rates("pricing/rates.yaml")


def conv(scenario_id: str = "s1", conversation_id: str = "c1") -> Conversation:
    return Conversation(
        conversation_id=conversation_id, agent_version="v1", scenario_id=scenario_id,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        end_reason=EndReason.caller_hangup,
    )


def asr(sid: str, *, transcript: str = "hello", start=0, dur=500) -> AsrTranscribe:
    return AsrTranscribe(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        gen_ai_system="deepgram", gen_ai_request_model="nova-3",
        audio_seconds=1.0, is_streaming=True, transcript=transcript, confidence=0.9,
    )


def llm(sid: str, *, start=0, dur=500, model="gpt-5", input_tokens=500, output_tokens=15,
        decision_kind=DecisionKind.route, decision_chosen="x", output_text="x",
        cache_read_tokens=0) -> LlmDecide:
    return LlmDecide(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        gen_ai_system="openai", gen_ai_request_model=model,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        decision_kind=decision_kind, decision_chosen=decision_chosen,
        decision_candidates=[decision_chosen], output_text=output_text, latency_ms=dur,
    )


def tool(sid: str, *, start=0, dur=500, name="update_address", args_hash="sha256:h",
         cost_usd=0.0) -> ToolCall:
    return ToolCall(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        tool_name=name, args_hash=args_hash, args_json="{}", result_hash="sha256:r",
        latency_ms=dur, cost_usd=cost_usd, tool_kind=ToolKind.lookup,
    )


def turn(idx: int, *, wall_start=0, wall_end=1000, asr_spans=(), llm_spans=(),
         tools_spans=(), speaker_first="agent") -> Turn:
    return Turn(
        turn_index=idx, speaker_first=speaker_first, wall_start_ms=wall_start,
        wall_end_ms=wall_end, asr=list(asr_spans), llm=list(llm_spans),
        tools=list(tools_spans),
    )


def trace(*turns: Turn, scenario_id: str = "s1", conversation_id: str = "c1") -> Trace:
    return Trace(conversation=conv(scenario_id=scenario_id, conversation_id=conversation_id),
                 turns=list(turns))


def priced(*turns: Turn, scenario_id: str = "s1", conversation_id: str = "c1") -> PricedTrace:
    return price_trace(
        trace(*turns, scenario_id=scenario_id, conversation_id=conversation_id), RATES
    )
