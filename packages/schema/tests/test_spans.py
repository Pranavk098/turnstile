import pytest
from pydantic import ValidationError
from turnstile_schema.spans import AsrTranscribe, ContextAssemble, VadSegment

def test_asr_parses_otel_dotted_keys():
    span = AsrTranscribe.model_validate({
        "span_id": "s1",
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
            "span_id": "s1", "gen_ai.system": "deepgram",
            "gen_ai.request.model": "nova-3", "turnstile.audio_seconds": 1.0,
            "turnstile.is_streaming": True, "turnstile.transcript": "x",
            "turnstile.confidence": 0.9, "turnstile.bogus": 1})

def test_vad_allows_extra_because_uncontracted():
    v = VadSegment.model_validate({"span_id": "s1", "turnstile.anything": 5})
    assert v.span_id == "s1"

def test_context_assemble_parses():
    c = ContextAssemble.model_validate({
        "span_id": "s1", "turnstile.context_tokens": 3840,
        "turnstile.history_tokens": 2900, "turnstile.system_tokens": 620,
        "turnstile.retrieved_tokens": 320, "turnstile.retrieved_doc_ids": ["kb_412"],
        "turnstile.pruning_strategy": "none"})
    assert c.context_tokens == 3840

from turnstile_schema.spans import LlmDecide, ToolCall

def test_llm_decide_full_parse_and_defaults():
    s = LlmDecide.model_validate({
        "span_id": "s1", "gen_ai.system": "openai",
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
            "span_id": "s1", "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 5,
            "turnstile.decision_chosen": "x", "turnstile.decision_candidates": ["x"],
            "turnstile.output_text": "x", "turnstile.latency_ms": 1})

def test_tool_call_parse_and_default_cost():
    t = ToolCall.model_validate({
        "span_id": "s1", "turnstile.tool_name": "lookup_order",
        "turnstile.args_hash": "sha256:aa", "turnstile.args_json": "{}",
        "turnstile.result_hash": "sha256:bb", "turnstile.latency_ms": 340,
        "turnstile.tool_kind": "lookup"})
    assert t.cost_usd == 0.0 and t.tool_kind.value == "lookup"
