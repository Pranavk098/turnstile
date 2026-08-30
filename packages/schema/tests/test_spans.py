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
