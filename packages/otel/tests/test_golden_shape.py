"""The Trace a TraceRecorder produces must reproduce the SHAPE of a golden
fixture: same span types present per turn, and a tool carrying
tool_status/effect (schema v1.1 amendment T3). Exact timings are not
compared -- fixtures are hand-authored, the recorder is clock-driven; only
the span-type structure per turn is a contract both must satisfy."""
from __future__ import annotations

from pathlib import Path

from turnstile_schema import load_trace
from turnstile_otel import TraceRecorder

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"


def _shape(trace) -> list[dict]:
    """(span-type -> count) per turn, in turn order -- the structural
    fingerprint we compare against the fixture."""
    out = []
    for turn in trace.turns:
        out.append(
            {
                "asr": len(turn.asr),
                "context": 0 if turn.context is None else 1,
                "llm": len(turn.llm),
                "tools": len(turn.tools),
                "tts": len(turn.tts),
                "playback": len(turn.playback),
            }
        )
    return out


def _record_baseline_shaped_trace() -> "Trace":
    """Scripts a 3-turn conversation through the recorder matching
    00_baseline_clean's structure: turn0 llm+tts+playback, turn1
    llm+tool(lookup)+tts+playback, turn2 llm+tts+playback."""
    ticks = iter(float(i) for i in range(1, 1000))
    clock = lambda: next(ticks)  # noqa: E731 -- simple monotonically-increasing fake

    rec = TraceRecorder("conv-shape", "agent@test", "order_status", clock=clock)

    with rec.start_turn(0, "caller") as turn:
        turn.record_llm(
            gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
            input_tokens=600, output_tokens=12, decision_kind="route",
            decision_chosen="order_status", decision_candidates=["order_status", "billing"],
            output_text="Let me check that.",
        )
        turn.record_tts(
            gen_ai_system="piper", text="Let me check that.",
            audio_seconds_generated=1.4,
        )
        turn.record_playback(chars_played=18, audio_seconds_played=1.4)

    with rec.start_turn(1, "agent") as turn:
        turn.record_llm(
            gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
            input_tokens=900, output_tokens=20, decision_kind="compose",
            decision_chosen="report_status", decision_candidates=["report_status"],
            output_text="Your order ships tomorrow.",
        )
        turn.record_tool(
            tool_name="lookup_order", tool_kind="lookup",
            tool_status="ok", effect="none", args={"order_id": "A1"},
        )
        turn.record_tts(
            gen_ai_system="piper", text="Your order ships tomorrow.",
            audio_seconds_generated=2.0,
        )
        turn.record_playback(chars_played=26, audio_seconds_played=2.0)

    with rec.start_turn(2, "caller") as turn:
        turn.record_llm(
            gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
            input_tokens=700, output_tokens=10, decision_kind="compose",
            decision_chosen="farewell", decision_candidates=["farewell"],
            output_text="Anything else? Goodbye.",
        )
        turn.record_tts(
            gen_ai_system="piper", text="Anything else? Goodbye.",
            audio_seconds_generated=1.6,
        )
        turn.record_playback(chars_played=23, audio_seconds_played=1.6)

    rec.record_telephony("twilio", "inbound", billable_seconds=12)
    return rec.finalize("caller_hangup")


def test_recorded_trace_matches_baseline_fixture_shape():
    golden = load_trace(GOLDEN / "00_baseline_clean.json")
    recorded = _record_baseline_shaped_trace()

    assert len(recorded.turns) == len(golden.turns)
    assert _shape(recorded) == _shape(golden)


def test_recorded_trace_has_valid_telephony_leg_like_fixture():
    recorded = _record_baseline_shaped_trace()
    assert recorded.telephony is not None
    assert recorded.telephony.provider == "twilio"
    assert recorded.telephony.direction.value == "inbound"


def test_recorded_handoff_tool_carries_tool_status_and_effect():
    """Mirrors 09_escalation_debt's handoff tool span: tool_kind=handoff,
    tool_status=ok, effect=committed."""
    ticks = iter(float(i) for i in range(1, 1000))
    clock = lambda: next(ticks)  # noqa: E731

    rec = TraceRecorder("conv-handoff", "agent@test", "billing_dispute", clock=clock)
    with rec.start_turn(0, "agent") as turn:
        turn.record_llm(
            gen_ai_system="openai", gen_ai_request_model="gpt-5-mini",
            input_tokens=650, output_tokens=18, decision_kind="compose",
            decision_chosen="transfer", decision_candidates=["transfer"],
            output_text="Transferring you now.",
        )
        tool = turn.record_tool(
            tool_name="transfer_to_agent", tool_kind="handoff",
            tool_status="ok", effect="committed",
        )
        turn.record_tts(
            gen_ai_system="piper", text="Transferring you now.",
            audio_seconds_generated=1.5,
        )
        turn.record_playback(chars_played=22, audio_seconds_played=1.5)

    trace = rec.finalize("escalated")

    recorded_tool = trace.turns[0].tools[0]
    assert recorded_tool.tool_kind.value == "handoff"
    assert recorded_tool.tool_status.value == "ok"
    assert recorded_tool.effect.value == "committed"
    assert tool.tool_kind.value == "handoff"
