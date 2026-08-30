from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from turnstile_schema.enums import PruningStrategy

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")

class Span(BaseModel):
    model_config = _STRICT
    span_id: str

class VadSegment(Span):
    # PRD does not freeze VAD attributes; allow extra so we do not invent contract.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

class AsrTranscribe(Span):
    gen_ai_system: str = Field(alias="gen_ai.system")
    gen_ai_request_model: str = Field(alias="gen_ai.request.model")
    audio_seconds: float = Field(alias="turnstile.audio_seconds")
    is_streaming: bool = Field(alias="turnstile.is_streaming")
    transcript: str = Field(alias="turnstile.transcript")
    confidence: float = Field(alias="turnstile.confidence")

class ContextAssemble(Span):
    context_tokens: int = Field(alias="turnstile.context_tokens")
    history_tokens: int = Field(alias="turnstile.history_tokens")
    system_tokens: int = Field(alias="turnstile.system_tokens")
    retrieved_tokens: int = Field(alias="turnstile.retrieved_tokens")
    retrieved_doc_ids: list[str] = Field(alias="turnstile.retrieved_doc_ids")
    pruning_strategy: PruningStrategy = Field(alias="turnstile.pruning_strategy")

# Placeholders kept so trace.py imports still resolve until Tasks 4-5 replace them.
class LlmDecide(Span): ...
class ToolCall(Span): ...
class TtsSynthesize(Span): ...
class AudioPlayback(Span): ...
