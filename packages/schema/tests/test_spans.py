import pytest
from pydantic import ValidationError
from turnstile_schema.spans import AsrTranscribe, ContextAssemble, VadSegment

def test_asr_parses_otel_dotted_keys():
    span = AsrTranscribe.model_validate({
        "span_id": "s1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 500,
        "gen_ai.system": "deepgram",
        "gen_ai.request.model": "nova-3",
        "turnstile.audio_seconds": 4.82,
        "turnstile.is_streaming": True,
        "turnstile.transcript": "hello",
        "turnstile.confidence": 0.94,
    })
    assert span.audio_seconds == 4.82
    assert span.gen_ai_system == "deepgram"

def test_asr_forbids_unknown_attribute():
    with pytest.raises(ValidationError):
        AsrTranscribe.model_validate({
            "span_id": "s1",
            "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 500,
            "gen_ai.system": "deepgram",
            "gen_ai.request.model": "nova-3", "turnstile.audio_seconds": 1.0,
            "turnstile.is_streaming": True, "turnstile.transcript": "x",
            "turnstile.confidence": 0.9, "turnstile.bogus": 1})

def test_span_requires_start_offset_and_duration():
    with pytest.raises(ValidationError):
        AsrTranscribe.model_validate({
            "span_id": "s1", "gen_ai.system": "deepgram",
            "gen_ai.request.model": "nova-3", "turnstile.audio_seconds": 1.0,
            "turnstile.is_streaming": True, "turnstile.transcript": "x",
            "turnstile.confidence": 0.9})

def test_vad_allows_extra_because_uncontracted():
    v = VadSegment.model_validate({
        "span_id": "s1", "turnstile.start_offset_ms": 0,
        "turnstile.duration_ms": 100, "turnstile.anything": 5})
    assert v.span_id == "s1"

def test_context_assemble_parses():
    c = ContextAssemble.model_validate({
        "span_id": "s1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 50,
        "turnstile.context_tokens": 3840,
        "turnstile.history_tokens": 2900, "turnstile.system_tokens": 620,
        "turnstile.retrieved_tokens": 320, "turnstile.retrieved_doc_ids": ["kb_412"],
        "turnstile.pruning_strategy": "none"})
    assert c.context_tokens == 3840

from turnstile_schema.spans import LlmDecide, ToolCall  # noqa: E402 -- grouped with its section

def test_llm_decide_full_parse_and_defaults():
    s = LlmDecide.model_validate({
        "span_id": "s1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 820,
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-5",
        "gen_ai.usage.input_tokens": 3840, "gen_ai.usage.output_tokens": 28,
        "turnstile.decision_kind": "route", "turnstile.decision_chosen": "lookup_order",
        "turnstile.decision_candidates": ["lookup_order", "escalate"],
        "turnstile.output_text": "ok", "turnstile.latency_ms": 820})
    assert s.decision_kind.value == "route"
    assert s.cache_read_tokens == 0 and s.reasoning_tokens == 0
    assert s.retry_of is None

def test_llm_decide_requires_decision_kind():
    with pytest.raises(ValidationError):
        LlmDecide.model_validate({
            "span_id": "s1",
            "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 1,
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 5,
            "turnstile.decision_chosen": "x", "turnstile.decision_candidates": ["x"],
            "turnstile.output_text": "x", "turnstile.latency_ms": 1})

def test_tool_call_parse_and_default_cost():
    t = ToolCall.model_validate({
        "span_id": "s1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 340,
        "turnstile.tool_name": "lookup_order",
        "turnstile.args_hash": "sha256:aa", "turnstile.args_json": "{}",
        "turnstile.result_hash": "sha256:bb", "turnstile.latency_ms": 340,
        "turnstile.tool_kind": "lookup"})
    assert t.cost_usd == 0.0 and t.tool_kind.value == "lookup"
    assert t.tool_status.value == "ok" and t.effect.value == "none"

def _tool_kwargs(**overrides):
    base = {
        "span_id": "s1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 340,
        "turnstile.tool_name": "process_refund",
        "turnstile.args_hash": "sha256:aa", "turnstile.args_json": "{}",
        "turnstile.result_hash": "sha256:bb", "turnstile.latency_ms": 340,
        "turnstile.tool_kind": "mutation"}
    base.update(overrides)
    return base

def test_tool_call_accepts_tool_status_and_effect_via_alias():
    t = ToolCall.model_validate(_tool_kwargs(
        **{"turnstile.tool_status": "ok", "turnstile.effect": "committed"}))
    assert t.tool_status.value == "ok" and t.effect.value == "committed"

def test_mutation_with_effect_none_is_rejected():
    with pytest.raises(ValidationError):
        ToolCall.model_validate(_tool_kwargs(
            **{"turnstile.tool_kind": "mutation", "turnstile.effect": "none"}))

def test_lookup_with_effect_committed_is_rejected():
    with pytest.raises(ValidationError):
        ToolCall.model_validate(_tool_kwargs(
            **{"turnstile.tool_kind": "lookup", "turnstile.effect": "committed"}))

def test_handoff_with_effect_none_is_rejected():
    with pytest.raises(ValidationError):
        ToolCall.model_validate(_tool_kwargs(
            **{"turnstile.tool_kind": "handoff", "turnstile.effect": "none"}))

def test_error_status_with_effect_committed_is_rejected():
    with pytest.raises(ValidationError):
        ToolCall.model_validate(_tool_kwargs(
            **{"turnstile.tool_kind": "mutation", "turnstile.tool_status": "error",
               "turnstile.effect": "committed"}))

def test_mutation_with_effect_committed_is_accepted():
    t = ToolCall.model_validate(_tool_kwargs(
        **{"turnstile.tool_kind": "mutation", "turnstile.effect": "committed"}))
    assert t.effect.value == "committed"

def test_handoff_with_effect_rejected_is_accepted():
    t = ToolCall.model_validate(_tool_kwargs(
        **{"turnstile.tool_kind": "handoff", "turnstile.effect": "rejected"}))
    assert t.effect.value == "rejected"

def test_lookup_with_effect_none_is_accepted():
    t = ToolCall.model_validate(_tool_kwargs(
        **{"turnstile.tool_kind": "lookup", "turnstile.effect": "none"}))
    assert t.effect.value == "none"

from turnstile_schema.spans import TtsSynthesize, AudioPlayback, TelephonyLeg  # noqa: E402 -- grouped with its section

def test_tts_and_playback_gap_is_representable():
    tts = TtsSynthesize.model_validate({
        "span_id": "t1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 11200,
        "gen_ai.system": "piper",
        "turnstile.chars_synthesized": 184,
        "turnstile.audio_seconds_generated": 11.2, "turnstile.text": "hi"})
    pb = AudioPlayback.model_validate({
        "span_id": "p1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 3800,
        "turnstile.chars_played": 61,
        "turnstile.audio_seconds_played": 3.8, "turnstile.truncated_by": "barge_in"})
    assert tts.chars_synthesized > pb.chars_played          # Detector 7 precondition
    assert pb.truncated_by == "barge_in"

def test_playback_truncated_by_defaults_none():
    pb = AudioPlayback.model_validate({
        "span_id": "p1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 3800,
        "turnstile.chars_played": 61,
        "turnstile.audio_seconds_played": 3.8})
    assert pb.truncated_by is None

def test_telephony_leg_parse():
    leg = TelephonyLeg.model_validate({
        "span_id": "leg1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 184000,
        "turnstile.provider": "twilio",
        "turnstile.direction": "inbound", "turnstile.billable_seconds": 184})
    assert leg.billable_seconds == 184
