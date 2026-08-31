"""Core TraceRecorder behavior: a scripted mini conversation through a fake,
injected clock must produce a schema-valid Trace with start_offset_ms /
duration_ms derived exactly from that clock (PRD Sec.3, schema v1.1
amendment T1 -- every span carries absolute offsets)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from turnstile_schema import Trace
from turnstile_otel import TraceRecorder


class FakeClock:
    """A deterministic stand-in for time.monotonic(): each call returns the
    next value from a pre-scripted sequence, in seconds (matching
    time.monotonic's unit), so every offset in the resulting trace is
    predictable from this script alone."""

    def __init__(self, ticks: list[float]) -> None:
        self._ticks = iter(ticks)
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return next(self._ticks)


def _make_recorder(ticks: list[float]) -> tuple[TraceRecorder, FakeClock]:
    clock = FakeClock(ticks)
    rec = TraceRecorder(
        conversation_id="conv-1",
        agent_version="agent@test",
        scenario_id="order_status",
        clock=clock,
    )
    return rec, clock


def test_two_turn_conversation_produces_valid_trace_with_clock_derived_offsets():
    # Clock script (seconds): index 0 is TraceRecorder.__init__ (t0 = 0.0).
    # Turn 0: enter @0.0s, asr ends @0.5s, llm ends @0.9s, tts ends @2.1s,
    #         playback ends @3.5s, exit @3.5s.
    # Turn 1: enter @3.5s, llm ends @4.2s, tts ends @5.4s, playback ends @6.8s,
    #         exit @6.8s.
    ticks = [
        0.0,  # __init__ t0
        0.0,  # turn0 __enter__ (wall_start)
        0.5,  # record_asr end
        0.9,  # record_llm end
        2.1,  # record_tts end
        3.5,  # record_playback end
        3.5,  # turn0 __exit__ (wall_end)
        3.5,  # turn1 __enter__ (wall_start)
        4.2,  # record_llm end
        5.4,  # record_tts end
        6.8,  # record_playback end
        6.8,  # turn1 __exit__ (wall_end)
        6.8,  # finalize() total_ms
    ]
    rec, clock = _make_recorder(ticks)

    with rec.start_turn(0, "caller") as turn:
        asr = turn.record_asr(
            gen_ai_system="deepgram", gen_ai_request_model="nova-3",
            audio_seconds=2.0, is_streaming=True, transcript="hello",
            confidence=0.95,
        )
        llm = turn.record_llm(
            gen_ai_system="anthropic", gen_ai_request_model="claude-sonnet-4-6",
            input_tokens=500, output_tokens=15, decision_kind="route",
            decision_chosen="order_status", decision_candidates=["order_status"],
            output_text="Let me check that.",
        )
        tts = turn.record_tts(
            gen_ai_system="cartesia", text="Let me check that.",
            audio_seconds_generated=1.4,
        )
        playback = turn.record_playback(chars_played=18, audio_seconds_played=1.4)

    with rec.start_turn(1, "agent") as turn1:
        llm1 = turn1.record_llm(
            gen_ai_system="anthropic", gen_ai_request_model="claude-sonnet-4-6",
            input_tokens=700, output_tokens=20, decision_kind="compose",
            decision_chosen="report_status", decision_candidates=["report_status"],
            output_text="Your order ships tomorrow.",
        )
        tts1 = turn1.record_tts(
            gen_ai_system="cartesia", text="Your order ships tomorrow.",
            audio_seconds_generated=2.0,
        )
        playback1 = turn1.record_playback(chars_played=26, audio_seconds_played=2.0)

    trace = rec.finalize("caller_hangup")

    # -- schema validity ----------------------------------------------------
    assert isinstance(trace, Trace)
    Trace.model_validate(trace.model_dump(by_alias=True))  # round-trips clean

    # -- offsets/durations derived from the fake clock, turn 0 --------------
    assert asr.start_offset_ms == 0
    assert asr.duration_ms == 500
    assert llm.start_offset_ms == 500
    assert llm.duration_ms == 400
    assert tts.start_offset_ms == 900
    assert tts.duration_ms == 1200
    assert playback.start_offset_ms == 2100
    assert playback.duration_ms == 1400

    assert trace.turns[0].wall_start_ms == 0
    assert trace.turns[0].wall_end_ms == 3500

    # -- turn 1 picks up where turn 0 left off -------------------------------
    assert trace.turns[1].wall_start_ms == 3500
    assert llm1.start_offset_ms == 3500
    assert llm1.duration_ms == 700
    assert tts1.start_offset_ms == 4200
    assert playback1.start_offset_ms == 5400
    assert trace.turns[1].wall_end_ms == 6800

    # llm.decide latency_ms defaults to duration_ms when not overridden
    assert llm.latency_ms == llm.duration_ms
    assert llm1.latency_ms == llm1.duration_ms

    assert trace.conversation.conversation_id == "conv-1"
    assert trace.conversation.end_reason.value == "caller_hangup"
    assert len(trace.turns) == 2
    assert clock.calls == len(ticks)


def test_record_telephony_spans_whole_conversation_duration():
    ticks = [0.0, 0.0, 1.0, 1.0, 4.0]  # init, enter, asr-end, exit, finalize
    rec, _ = _make_recorder(ticks)
    with rec.start_turn(0, "caller") as turn:
        turn.record_asr(
            gen_ai_system="deepgram", gen_ai_request_model="nova-3",
            audio_seconds=1.0, is_streaming=False, transcript="hi", confidence=0.9,
        )
    rec.record_telephony("twilio", "inbound", billable_seconds=4)
    trace = rec.finalize("caller_hangup")

    assert trace.telephony is not None
    assert trace.telephony.start_offset_ms == 0
    assert trace.telephony.duration_ms == 4000
    assert trace.telephony.provider == "twilio"
    assert trace.telephony.billable_seconds == 4


def test_no_telephony_is_optional_on_trace():
    ticks = [0.0, 0.0]
    rec, _ = _make_recorder(ticks)
    trace = rec.finalize("agent_hangup")
    assert trace.telephony is None
    assert trace.turns == []


def test_finalize_twice_raises():
    ticks = [0.0, 0.0]
    rec, _ = _make_recorder(ticks)
    rec.finalize("agent_hangup")
    with pytest.raises(RuntimeError):
        rec.finalize("agent_hangup")


def test_record_tool_respects_schema_effect_validator():
    """The shim must not bypass ToolCall's tool_kind x effect x tool_status
    validator (schema v1.1 amendment T3): lookup/retrieval must be
    effect=none."""
    ticks = [0.0, 0.0, 1.0]
    rec, _ = _make_recorder(ticks)
    with pytest.raises(ValidationError):
        with rec.start_turn(0, "caller") as turn:
            turn.record_tool(
                tool_name="lookup_order", tool_kind="lookup",
                effect="committed",  # illegal: lookup must be effect=none
            )


def test_record_tool_captures_status_and_effect_for_mutation():
    ticks = [0.0, 0.0, 1.0, 1.0]
    rec, _ = _make_recorder(ticks)
    with rec.start_turn(0, "agent") as turn:
        tool = turn.record_tool(
            tool_name="process_refund", tool_kind="mutation",
            tool_status="ok", effect="committed",
            args={"order_id": "A1"}, result={"status": "processed"},
        )
    assert tool.tool_status.value == "ok"
    assert tool.effect.value == "committed"
    assert tool.args_hash.startswith("sha256:")
    assert tool.result_hash.startswith("sha256:")
