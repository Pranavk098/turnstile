"""The shim must emit real OpenTelemetry spans, not just build the schema
Trace. Uses opentelemetry-sdk's InMemorySpanExporter (a SimpleSpanProcessor
flushes synchronously, so spans are visible immediately after each call --
no exporter.force_flush() polling needed) to assert the exported spans carry
the gen_ai.* / turnstile.* attributes documented in PRD Sec.3.2."""
from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from turnstile_otel import TraceRecorder


def _recorder_with_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    ticks = iter(float(i) for i in range(1, 1000))
    clock = lambda: next(ticks)  # noqa: E731

    rec = TraceRecorder(
        "conv-otel", "agent@test", "order_status",
        clock=clock, tracer_provider=provider,
    )
    return rec, exporter


def _span_by_name(exporter: InMemorySpanExporter, name: str):
    matches = [s for s in exporter.get_finished_spans() if s.name == name]
    assert matches, f"no exported span named {name!r}; got {[s.name for s in exporter.get_finished_spans()]}"
    return matches[0]


def test_conversation_and_turn_spans_are_emitted():
    rec, exporter = _recorder_with_exporter()
    with rec.start_turn(0, "caller"):
        pass
    rec.finalize("caller_hangup")

    names = [s.name for s in exporter.get_finished_spans()]
    assert "conversation" in names
    assert "turn" in names

    conv_span = _span_by_name(exporter, "conversation")
    assert conv_span.attributes["turnstile.conversation_id"] == "conv-otel"
    assert conv_span.attributes["turnstile.schema_version"] == "1.1"
    assert conv_span.attributes["turnstile.end_reason"] == "caller_hangup"


def test_llm_span_carries_gen_ai_attributes():
    rec, exporter = _recorder_with_exporter()
    with rec.start_turn(0, "caller") as turn:
        turn.record_llm(
            gen_ai_system="anthropic", gen_ai_request_model="claude-sonnet-4-6",
            input_tokens=3840, output_tokens=28, decision_kind="tool_select",
            decision_chosen="lookup_order", decision_candidates=["lookup_order", "escalate"],
            output_text="Checking your order.",
        )
    rec.finalize("caller_hangup")

    llm_span = _span_by_name(exporter, "llm.decide")
    attrs = llm_span.attributes
    assert attrs["gen_ai.system"] == "anthropic"
    assert attrs["gen_ai.request.model"] == "claude-sonnet-4-6"
    assert attrs["gen_ai.usage.input_tokens"] == 3840
    assert attrs["gen_ai.usage.output_tokens"] == 28
    assert attrs["turnstile.decision_kind"] == "tool_select"
    assert attrs["turnstile.decision_chosen"] == "lookup_order"
    assert tuple(attrs["turnstile.decision_candidates"]) == ("lookup_order", "escalate")


def test_asr_and_tts_spans_carry_gen_ai_system():
    rec, exporter = _recorder_with_exporter()
    with rec.start_turn(0, "caller") as turn:
        turn.record_asr(
            gen_ai_system="deepgram", gen_ai_request_model="nova-3",
            audio_seconds=4.82, is_streaming=True, transcript="I need help",
            confidence=0.94,
        )
        turn.record_tts(
            gen_ai_system="cartesia", text="Sure thing.",
            audio_seconds_generated=0.8,
        )
    rec.finalize("caller_hangup")

    asr_span = _span_by_name(exporter, "asr.transcribe")
    assert asr_span.attributes["gen_ai.system"] == "deepgram"
    assert asr_span.attributes["gen_ai.request.model"] == "nova-3"
    assert asr_span.attributes["turnstile.transcript"] == "I need help"

    tts_span = _span_by_name(exporter, "tts.synthesize")
    assert tts_span.attributes["gen_ai.system"] == "cartesia"
    assert tts_span.attributes["turnstile.chars_synthesized"] == len("Sure thing.")


def test_tool_call_span_carries_tool_status_and_effect():
    rec, exporter = _recorder_with_exporter()
    with rec.start_turn(0, "agent") as turn:
        turn.record_tool(
            tool_name="process_refund", tool_kind="mutation",
            tool_status="ok", effect="pending", args={"order_id": "A1"},
        )
    rec.finalize("caller_hangup")

    tool_span = _span_by_name(exporter, "tool.call")
    assert tool_span.attributes["turnstile.tool_name"] == "process_refund"
    assert tool_span.attributes["turnstile.tool_status"] == "ok"
    assert tool_span.attributes["turnstile.effect"] == "pending"


def test_telephony_leg_span_is_emitted_as_sibling_of_conversation():
    rec, exporter = _recorder_with_exporter()
    with rec.start_turn(0, "caller"):
        pass
    rec.record_telephony("twilio", "inbound", billable_seconds=12)
    rec.finalize("caller_hangup")

    leg_span = _span_by_name(exporter, "telephony.leg")
    assert leg_span.attributes["turnstile.provider"] == "twilio"
    assert leg_span.attributes["turnstile.direction"] == "inbound"
    assert leg_span.attributes["turnstile.billable_seconds"] == 12

    conv_span = _span_by_name(exporter, "conversation")
    # telephony.leg is a sibling of the conversation root (PRD Sec.3.1), not
    # nested under it -- neither has the other as parent.
    assert leg_span.context.trace_id != 0
    assert leg_span.parent is None
