"""G1 contract tests -- the recorder must be able to EMIT real concurrency
(docs/GATES.md G1): TTS-during-LLM within a turn, and a next-turn llm.decide
overlapping the prior turn's audio.playback ("shape B", fixture 19). Until
this lands, union == sum on every live trace and Detector 8 systematically
over-reports silence -- these tests are the gate that makes D8's numbers
trustworthy.

Each test scripts a FakeClock and asserts (a) schema-validity of the produced
Trace, (b) the exact span intervals implied by the clock script, and (c) --
via turnstile_detectors.detect_silence_tax -- that the union computation sees
the overlap (union < sum) and that no false silence is reported on it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from turnstile_schema import Baselines, Verdict, VerdictLabel, Trace, load_rates
from turnstile_pricing import price_trace
from turnstile_detectors.d08_silence_tax import detect_silence_tax
from turnstile_otel import TraceRecorder

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

DUMMY_VERDICT = Verdict(label=VerdictLabel.RESOLVED, confidence=1.0, evidence=[], turn_of_no_return=None)
EMPTY_BASELINES = Baselines(per_intent={})


class FakeClock:
    """Same stand-in as test_recorder.py: each call returns the next scripted
    value, in seconds. Scripts must be non-decreasing (monotonic clock)."""

    def __init__(self, ticks: list[float]) -> None:
        self._ticks = iter(ticks)
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return next(self._ticks)


def _make_recorder(ticks: list[float]) -> tuple[TraceRecorder, FakeClock]:
    clock = FakeClock(ticks)
    rec = TraceRecorder(
        conversation_id="conv-g1",
        agent_version="agent@test",
        scenario_id="order_status",
        clock=clock,
    )
    return rec, clock


def _recorder_with_exporter(ticks: list[float]) -> tuple[TraceRecorder, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    clock = FakeClock(ticks)
    rec = TraceRecorder(
        conversation_id="conv-g1",
        agent_version="agent@test",
        scenario_id="order_status",
        clock=clock,
        tracer_provider=provider,
    )
    return rec, exporter


def _llm(turn, *, input_tokens=600, output_tokens=12, text="Let me check that."):
    return turn.record_llm(
        gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
        input_tokens=input_tokens, output_tokens=output_tokens, decision_kind="compose",
        decision_chosen="report_status", decision_candidates=["report_status"],
        output_text=text,
    )


def _tts(turn, text="Let me check that.", **timing):
    return turn.record_tts(
        gen_ai_system="piper", text=text,
        audio_seconds_generated=1.0, chars_synthesized=len(text), **timing,
    )


def _union_and_sum(trace: Trace) -> tuple[int, int]:
    """Trace-level union vs sum over every active span -- same math as
    packages/schema/tests/test_fixtures.py's _union_size/_covered_intervals."""
    intervals = []
    for turn in trace.turns:
        for spans in (turn.asr, turn.llm, turn.tools, turn.tts, turn.playback):
            for span in spans:
                intervals.append((span.start_offset_ms, span.start_offset_ms + span.duration_ms))
    summed = sum(e - s for s, e in intervals)
    union, cur_s, cur_e = 0, None, None
    for s, e in sorted(intervals):
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            union += cur_e - cur_s
            cur_s, cur_e = s, e
    if cur_s is not None:
        union += cur_e - cur_s
    return union, summed


def _priced(rec: TraceRecorder):
    trace = rec.finalize("caller_hangup")
    Trace.model_validate(trace.model_dump(by_alias=True, mode="json"))  # schema-valid
    pt = price_trace(trace, load_rates(RATES))
    return trace, pt


# --------------------------------------------------------------------------- #
# Intra-turn overlap: TTS streaming during LLM decode (the G1 headline case)  #
# --------------------------------------------------------------------------- #

def test_tts_during_llm_overlap_is_representable():
    # llm [0,820); tts starts 420ms INTO the llm span (D < llm duration) ->
    # [420,1240). Union = [0,1240) = 1240; sum = 820+820 = 1640; overlap 400.
    ticks = [0.0, 0.0, 0.82, 1.24, 1.24, 1.24]  # init, open, llm-end, tts-end, close, finalize
    rec, _ = _make_recorder(ticks)

    turn = rec.start_turn(0, "agent")
    llm = _llm(turn)
    tts = _tts(turn, into_previous_ms=420)
    turn.close()

    assert llm.start_offset_ms == 0 and llm.duration_ms == 820
    assert tts.start_offset_ms == 420 and tts.duration_ms == 820

    trace, pt = _priced(rec)
    union, summed = _union_and_sum(trace)
    assert summed - union == 400          # the union sees the overlap...
    assert summed > union > 0
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []  # ...counts once: no false silence


def test_absolute_at_ms_starts_mid_previous_span():
    # Same overlap expressed absolutely: llm [0,820); tts at_ms=420.
    ticks = [0.0, 0.0, 0.82, 1.24, 1.24, 1.24]
    rec, _ = _make_recorder(ticks)

    turn = rec.start_turn(0, "agent")
    _llm(turn)
    tts = _tts(turn, at_ms=420)
    turn.close()

    assert tts.start_offset_ms == 420 and tts.duration_ms == 820
    trace, pt = _priced(rec)
    union, summed = _union_and_sum(trace)
    assert summed - union == 400
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_overlapped_span_reaches_otel_with_its_absolute_timeline():
    # The real OTel span must carry the overlapped span's actual offset, not
    # a contiguous rewrite of it.
    ticks = [0.0, 0.0, 0.82, 1.24, 1.24, 1.24]
    rec, exporter = _recorder_with_exporter(ticks)
    turn = rec.start_turn(0, "agent")
    _llm(turn)
    _tts(turn, into_previous_ms=420)
    turn.close()
    rec.finalize("caller_hangup")

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    assert by_name["tts.synthesize"].attributes["turnstile.start_offset_ms"] == 420
    assert by_name["tts.synthesize"].attributes["turnstile.duration_ms"] == 820
    assert by_name["llm.decide"].attributes["turnstile.start_offset_ms"] == 0


# --------------------------------------------------------------------------- #
# Cross-turn overlap ("shape B", fixture 19): next-turn llm.decide overlapping #
# the prior turn's audio.playback. Live flow: VAD fires mid-playback -> turn 6 #
# opens at 2400; playback5 and llm6 are each recorded when they COMPLETE.     #
# --------------------------------------------------------------------------- #

def test_shape_b_cross_turn_overlap_reproduces_fixture_19():
    # t5: llm [0,500) tts [500,1700) playback [1700,2900); wall (0,2900)
    # t6: opens @2400 (mid-playback): llm [2400,2900) tts [2900,4100) pb [4100,5300)
    ticks = [
        0.0,   # init
        0.0,   # open turn 5 (wall_start + cursor)
        0.5,   # llm5 end
        1.7,   # tts5 end
        2.4,   # open turn 6 -- BEFORE turn 5 is closed or fully recorded
        2.9,   # playback5 end (recorded after turn 6 opened)
        2.9,   # close turn 5 (wall_end == playback end -> no trailing gap)
        2.9,   # llm6 end
        4.1,   # tts6 end
        5.3,   # playback6 end
        5.3,   # close turn 6
        5.3,   # finalize
    ]
    rec, _ = _make_recorder(ticks)

    turn5 = rec.start_turn(5, "agent")
    _llm(turn5, text="Checking now.")
    _tts(turn5, text="Checking now.")
    turn6 = rec.start_turn(6, "caller")  # VAD fires mid-playback
    turn5.record_playback(chars_played=18, audio_seconds_played=1.4)
    turn5.close()
    llm6 = _llm(turn6, text="Sure, go ahead.")
    turn6.record_tts(
        gen_ai_system="piper", text="Sure, go ahead.",
        audio_seconds_generated=1.2, chars_synthesized=len("Sure, go ahead."),
    )
    turn6.record_playback(chars_played=15, audio_seconds_played=1.2)
    turn6.close()

    trace, pt = _priced(rec)

    # span-level overlap: playback5 [1700,2900) X llm6 [2400,2900)
    pb5 = trace.turns[0].playback[0]
    assert (pb5.start_offset_ms, pb5.duration_ms) == (1700, 1200)
    assert (llm6.start_offset_ms, llm6.duration_ms) == (2400, 500)
    assert pb5.start_offset_ms + pb5.duration_ms > llm6.start_offset_ms
    # turn-wall overlap, exactly what the nested-with recorder could not emit
    assert trace.turns[0].wall_start_ms == 0 and trace.turns[0].wall_end_ms == 2900
    assert trace.turns[1].wall_start_ms == 2400 and trace.turns[1].wall_end_ms == 5300
    assert trace.turns[1].wall_start_ms < trace.turns[0].wall_end_ms

    union, summed = _union_and_sum(trace)
    assert summed - union == 500          # cross-turn overlap counted once
    # D8 must stay silent on the shape (fixture 19 has target_detector: none)
    assert detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


# --------------------------------------------------------------------------- #
# Fixture 08's shape: contiguous stages, trailing silence gap INTACT          #
# --------------------------------------------------------------------------- #

def test_fixture_08_shape_trailing_silence_gap_intact():
    # tool [0,300) llm [300,800) tts [800,1800); wall (0,7000) -> 5200ms dead
    # air with the meter running. The redesign must not change this shape.
    ticks = [0.0, 0.0, 0.3, 0.8, 1.8, 7.0, 7.0]  # init, open, tool, llm, tts, close, finalize
    rec, _ = _make_recorder(ticks)

    turn = rec.start_turn(0, "agent")
    turn.record_tool(
        tool_name="lookup_order", tool_kind="lookup",
        tool_status="ok", effect="none", args={"order_id": "A1"},
    )
    _llm(turn, text="Checking now.")
    _tts(turn, text="Checking now.")
    turn.close()
    rec.record_telephony("twilio", "inbound", billable_seconds=7)
    trace, pt = _priced(rec)

    findings = detect_silence_tax(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    ev = findings[0].evidence
    assert ev["silence_ms"] == 5200
    assert ev["trailing_gap"] is True
    assert ev["attributed_to"] == "asr_endpoint"  # tts -> asr_endpoint trailing fallback


# --------------------------------------------------------------------------- #
# Independent turn lifetimes: bookkeeping guarantees                          #
# --------------------------------------------------------------------------- #

def test_turns_are_ordered_by_index_regardless_of_close_order():
    ticks = [0.0, 0.0, 1.0, 1.5, 1.5, 2.0, 2.0, 2.0]  # init, open0, open1, llm1, close1, llm0, close0, finalize
    rec, _ = _make_recorder(ticks)
    turn0 = rec.start_turn(0, "caller")
    turn1 = rec.start_turn(1, "agent")
    _llm(turn1)
    turn1.close()
    _llm(turn0)  # turn 0's span recorded after turn 1 closed
    turn0.close()
    trace = rec.finalize("caller_hangup")
    assert [t.turn_index for t in trace.turns] == [0, 1]


def test_finalize_with_open_turn_raises():
    ticks = [0.0, 0.0]
    rec, _ = _make_recorder(ticks)
    rec.start_turn(0, "caller")
    with pytest.raises(RuntimeError, match="turn 0"):
        rec.finalize("caller_hangup")


def test_duplicate_turn_index_raises():
    ticks = [0.0, 0.0, 0.0]
    rec, _ = _make_recorder(ticks)
    rec.start_turn(0, "caller")
    with pytest.raises(ValueError, match="turn 0"):
        rec.start_turn(0, "agent")


def test_record_after_close_raises_and_double_close_raises():
    ticks = [0.0, 0.0, 0.5, 0.5, 0.5]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    _llm(turn)
    turn.close()
    with pytest.raises(RuntimeError, match="closed"):
        _llm(turn)
    with pytest.raises(RuntimeError, match="closed"):
        turn.close()


def test_abandon_drops_the_turn():
    ticks = [0.0, 0.0, 0.5, 0.0]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    _llm(turn)
    turn.abandon()
    trace = rec.finalize("caller_hangup")
    assert trace.turns == []


def test_abandon_twice_raises():
    ticks = [0.0, 0.0, 0.0, 0.0]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    turn.abandon()
    with pytest.raises(RuntimeError, match="abandoned"):
        turn.abandon()


# --------------------------------------------------------------------------- #
# Timing-argument error paths                                                 #
# --------------------------------------------------------------------------- #

def test_into_previous_ms_requires_a_previous_span():
    ticks = [0.0, 0.0, 0.5, 0.5]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    with pytest.raises(ValueError, match="into_previous_ms"):
        turn.record_playback(chars_played=1, audio_seconds_played=0.1, into_previous_ms=100)
    turn.abandon()


def test_at_ms_and_into_previous_ms_are_mutually_exclusive():
    ticks = [0.0, 0.0, 0.5, 0.5]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    _llm(turn)
    with pytest.raises(ValueError, match="mutually exclusive"):
        _tts(turn, at_ms=100, into_previous_ms=50)
    turn.abandon()


def test_negative_at_ms_raises():
    ticks = [0.0, 0.0, 0.5]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    with pytest.raises(ValueError, match="at_ms"):
        turn.record_llm(
            gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
            input_tokens=1, output_tokens=1, decision_kind="route",
            decision_chosen="x", decision_candidates=["x"], output_text="x",
            at_ms=-5,
        )
    turn.abandon()


def test_explicit_start_beyond_clock_raises():
    # Claimed start 5000ms with the clock only at 600ms -> negative duration:
    # a caller bug, must fail loudly, never clamp.
    ticks = [0.0, 0.0, 0.6, 0.6]
    rec, _ = _make_recorder(ticks)
    turn = rec.start_turn(0, "caller")
    with pytest.raises(ValueError, match="duration"):
        turn.record_llm(
            gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
            input_tokens=1, output_tokens=1, decision_kind="route",
            decision_chosen="x", decision_candidates=["x"], output_text="x",
            at_ms=5000,
        )
    turn.abandon()
