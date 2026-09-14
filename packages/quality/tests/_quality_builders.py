"""Small synthetic-trace builders shared by the quality test files
(mirrors packages/detectors/tests/_builders.py, factored out once here
since both dimension unit tests and calibration tests need the same
span/turn/trace shapes)."""
from __future__ import annotations

from datetime import datetime, timezone

from turnstile_schema import PricedTrace, Verdict
from turnstile_schema.enums import (
    DecisionKind,
    Effect,
    EndReason,
    ToolKind,
    ToolStatus,
)
from turnstile_schema.spans import AudioPlayback, LlmDecide, ToolCall, TtsSynthesize
from turnstile_schema.trace import Conversation, Trace, Turn

from turnstile_quality import evaluate_quality


def _conv(**over):
    kw = dict(
        conversation_id="c1", agent_version="v1", scenario_id="refund",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        end_reason=EndReason.caller_hangup,
    )
    kw.update(over)
    return Conversation(**kw)


def _llm(sid, kind=DecisionKind.compose, chosen="x", text="hello there",
         turn_start=0):
    return LlmDecide(
        span_id=sid, start_offset_ms=turn_start, duration_ms=500,
        gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
        input_tokens=100, output_tokens=10,
        decision_kind=kind, decision_chosen=chosen,
        decision_candidates=[chosen], output_text=text, latency_ms=500,
    )


def _tool(sid, name="do_thing", kind=ToolKind.mutation, effect=Effect.committed,
          start=0):
    return ToolCall(
        span_id=sid, start_offset_ms=start, duration_ms=100,
        tool_name=name, args_hash="sha256:a", args_json="{}",
        result_hash="sha256:r", latency_ms=100, tool_kind=kind,
        tool_status=ToolStatus.ok, effect=effect,
    )


def _tts(sid, chars=50, text="spoken words here", start=0):
    return TtsSynthesize(
        span_id=sid, start_offset_ms=start, duration_ms=1000,
        gen_ai_system="piper", chars_synthesized=chars,
        audio_seconds_generated=1.0, text=text,
    )


def _playback(sid, chars=50, truncated_by=None, start=0):
    return AudioPlayback(
        span_id=sid, start_offset_ms=start, duration_ms=1000,
        chars_played=chars, audio_seconds_played=1.0,
        truncated_by=truncated_by,
    )


def _turn(idx, *, llm=(), tools=(), tts=(), playback=(), barge_in=False,
          start=0, end=1000):
    return Turn(
        turn_index=idx, speaker_first="caller",
        wall_start_ms=start, wall_end_ms=end, barge_in=barge_in,
        llm=list(llm), tools=list(tools), tts=list(tts),
        playback=list(playback),
    )


def _priced(*turns, scenario="refund", end_reason=EndReason.caller_hangup):
    trace = Trace(conversation=_conv(scenario_id=scenario, end_reason=end_reason),
                  turns=list(turns), telephony=None)
    n = len(turns)
    return PricedTrace(
        trace=trace, span_costs={}, turn_costs=[0.0] * n, conv_cost=0.0,
        stage_costs={"asr": 0.0, "llm": 0.0, "tts": 0.0, "telephony": 0.0},
    )


def _verdict(label, turn_of_no_return=None):
    return Verdict(label=label, confidence=0.9, evidence=[],
                   turn_of_no_return=turn_of_no_return)


def _dims(priced, verdict):
    return {d.id: d for d in evaluate_quality(priced, verdict).dimensions}


__all__ = [
    "_conv",
    "_dims",
    "_llm",
    "_playback",
    "_priced",
    "_tool",
    "_tts",
    "_turn",
    "_verdict",
]
