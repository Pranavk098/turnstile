from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from turnstile_schema.enums import PruningStrategy, DecisionKind, ToolKind, Direction

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

class LlmDecide(Span):
    gen_ai_system: str = Field(alias="gen_ai.system")
    gen_ai_request_model: str = Field(alias="gen_ai.request.model")
    input_tokens: int = Field(alias="gen_ai.usage.input_tokens")
    output_tokens: int = Field(alias="gen_ai.usage.output_tokens")
    cache_read_tokens: int = Field(0, alias="turnstile.cache_read_tokens")
    cache_write_tokens: int = Field(0, alias="turnstile.cache_write_tokens")
    reasoning_tokens: int = Field(0, alias="turnstile.reasoning_tokens")
    decision_kind: DecisionKind = Field(alias="turnstile.decision_kind")
    decision_chosen: str = Field(alias="turnstile.decision_chosen")
    decision_candidates: list[str] = Field(alias="turnstile.decision_candidates")
    output_text: str = Field(alias="turnstile.output_text")
    latency_ms: int = Field(alias="turnstile.latency_ms")
    retry_of: str | None = Field(None, alias="turnstile.retry_of")

class ToolCall(Span):
    tool_name: str = Field(alias="turnstile.tool_name")
    args_hash: str = Field(alias="turnstile.args_hash")
    args_json: str = Field(alias="turnstile.args_json")
    result_hash: str = Field(alias="turnstile.result_hash")
    latency_ms: int = Field(alias="turnstile.latency_ms")
    cost_usd: float = Field(0.0, alias="turnstile.cost_usd")
    tool_kind: ToolKind = Field(alias="turnstile.tool_kind")

class TtsSynthesize(Span):
    gen_ai_system: str = Field(alias="gen_ai.system")
    chars_synthesized: int = Field(alias="turnstile.chars_synthesized")
    audio_seconds_generated: float = Field(alias="turnstile.audio_seconds_generated")
    text: str = Field(alias="turnstile.text")

class AudioPlayback(Span):
    chars_played: int = Field(alias="turnstile.chars_played")
    audio_seconds_played: float = Field(alias="turnstile.audio_seconds_played")
    truncated_by: Literal["barge_in", "hangup"] | None = Field(
        None, alias="turnstile.truncated_by")

class TelephonyLeg(Span):
    provider: str = Field(alias="turnstile.provider")
    direction: Direction = Field(alias="turnstile.direction")
    billable_seconds: int = Field(alias="turnstile.billable_seconds")
