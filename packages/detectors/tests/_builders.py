"""Small synthetic-trace builders shared by the detector unit-test files
(mirrors the small per-file builder helpers in packages/pricing/tests and
packages/verdict/tests, factored out once here since five detector test files
need the same span/turn/trace shapes)."""
from __future__ import annotations

from datetime import datetime, timezone

from turnstile_schema import Baselines, PricedTrace, RateTable, Verdict
from turnstile_schema.enums import DecisionKind, Direction, EndReason, ToolKind, VerdictLabel
from turnstile_schema.rates import AsrRate, LlmRate, TelephonyRate, TtsRate
from turnstile_schema.spans import (
    AudioPlayback, ContextAssemble, LlmDecide, TelephonyLeg, ToolCall, TtsSynthesize,
)
from turnstile_schema.trace import Conversation, Trace, Turn
from turnstile_pricing import price_trace

DUMMY_VERDICT = Verdict(label=VerdictLabel.RESOLVED, confidence=1.0, evidence=[], turn_of_no_return=None)
EMPTY_BASELINES = Baselines(per_intent={})


def conv() -> Conversation:
    return Conversation(
        conversation_id="c1", agent_version="v1", scenario_id="s1",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        end_reason=EndReason.caller_hangup,
    )


def llm(sid, *, start, dur=500, input_tokens, output_tokens, decision_kind=DecisionKind.compose,
        output_text="x", cache_read_tokens=0, model="gpt-5-mini") -> LlmDecide:
    return LlmDecide(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        gen_ai_system="openai", gen_ai_request_model=model,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        decision_kind=decision_kind, decision_chosen="x", decision_candidates=["x"],
        output_text=output_text, latency_ms=dur,
    )


def tool(sid, *, start, dur=300, name="do_thing", args_hash="sha256:a",
         kind=ToolKind.mutation, cost_usd=0.0, args_json="{}", effect=None) -> ToolCall:
    return ToolCall(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        tool_name=name, args_hash=args_hash, args_json=args_json, result_hash="sha256:r",
        latency_ms=dur, cost_usd=cost_usd, tool_kind=kind,
        effect=effect if effect is not None else (
            "committed" if kind in (ToolKind.mutation, ToolKind.handoff) else "none"
        ),
    )


def context(sid, *, start, dur=80, context_tokens=900, history_tokens=200, system_tokens=100,
            retrieved_tokens=600, retrieved_doc_ids=None) -> ContextAssemble:
    return ContextAssemble(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        context_tokens=context_tokens, history_tokens=history_tokens, system_tokens=system_tokens,
        retrieved_tokens=retrieved_tokens, retrieved_doc_ids=list(retrieved_doc_ids or []),
        pruning_strategy="none",
    )


def tts(sid, *, start, dur=1000, chars, text="x") -> TtsSynthesize:
    return TtsSynthesize(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        gen_ai_system="piper", chars_synthesized=chars,
        audio_seconds_generated=dur / 1000.0, text=text,
    )


def playback(sid, *, start, dur=1000, chars, truncated_by=None) -> AudioPlayback:
    return AudioPlayback(
        span_id=sid, start_offset_ms=start, duration_ms=dur,
        chars_played=chars, audio_seconds_played=dur / 1000.0, truncated_by=truncated_by,
    )


def leg(*, billable_seconds=60, provider="twilio", direction=Direction.inbound,
        dur=60_000) -> TelephonyLeg:
    return TelephonyLeg(
        span_id="leg", start_offset_ms=0, duration_ms=dur,
        provider=provider, direction=direction, billable_seconds=billable_seconds,
    )


def turn(idx, wall_start, wall_end, *, asr=(), llm_spans=(), tools=(), tts_spans=(), playback_spans=(),
         speaker_first="caller", context_span=None) -> Turn:
    return Turn(
        turn_index=idx, speaker_first=speaker_first, wall_start_ms=wall_start, wall_end_ms=wall_end,
        asr=list(asr), llm=list(llm_spans), tools=list(tools), tts=list(tts_spans),
        playback=list(playback_spans), context=context_span,
    )


def trace(*turns: Turn, telephony: TelephonyLeg | None = None) -> Trace:
    return Trace(conversation=conv(), turns=list(turns), telephony=telephony)


def rates() -> RateTable:
    """Mirrors pricing/rates.yaml's real numbers exactly (not arbitrary
    synthetic values): detectors load the real rates.yaml themselves
    (`detect()` has no rates param, PRD §5), so a PricedTrace built here with
    different numbers would make span_costs/turn_costs disagree with what a
    detector recomputes internally for its raw-rate formulas (PRD §6 D2/D6/D7).
    Keeping this table byte-identical to rates.yaml keeps the two in sync."""
    return RateTable(
        asr={"deepgram/nova-3": AsrRate(unit="audio_minute", rate=0.0043)},
        llm={
            "openai/gpt-5": LlmRate(unit="mtok", input=1.25, output=10.00, cache_read=0.125, cache_write=0.0),
            "openai/gpt-5-mini": LlmRate(unit="mtok", input=0.25, output=2.00, cache_read=0.025, cache_write=0.0),
            "openai/gpt-5-nano": LlmRate(unit="mtok", input=0.05, output=0.40, cache_read=0.005, cache_write=0.0),
        },
        tts={"piper": TtsRate(unit="char_1k", rate=0.025), "cartesia": TtsRate(unit="char_1k", rate=0.025)},
        telephony={"twilio/pstn_inbound": TelephonyRate(unit="minute", rate=0.0085)},
    )


def priced(*turns: Turn, telephony: TelephonyLeg | None = None) -> PricedTrace:
    """Build+price a synthetic trace. Uses the same rate numbers as the real
    pricing/rates.yaml (see `rates()`) so span_costs/turn_costs here agree
    with what a detector's own internal `get_rates()` (loading the real file)
    computes."""
    return price_trace(trace(*turns, telephony=telephony), rates())
