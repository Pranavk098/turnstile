from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from turnstile_schema.enums import EndReason, SpeakerFirst
from turnstile_schema.spans import (
    VadSegment, AsrTranscribe, ContextAssemble, LlmDecide,
    ToolCall, TtsSynthesize, AudioPlayback, TelephonyLeg,
)

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")

class Conversation(BaseModel):
    model_config = _STRICT
    conversation_id: str
    agent_version: str
    scenario_id: str
    started_at: datetime
    ended_at: datetime
    end_reason: EndReason
    schema_version: str = Field("1.1", alias="turnstile.schema_version")

class Turn(BaseModel):
    model_config = _STRICT
    turn_index: int
    speaker_first: SpeakerFirst
    wall_start_ms: int
    wall_end_ms: int
    barge_in: bool = False
    vad: list[VadSegment] = Field(default_factory=list)
    asr: list[AsrTranscribe] = Field(default_factory=list)
    context: ContextAssemble | None = None
    llm: list[LlmDecide] = Field(default_factory=list)
    tools: list[ToolCall] = Field(default_factory=list)
    tts: list[TtsSynthesize] = Field(default_factory=list)
    playback: list[AudioPlayback] = Field(default_factory=list)

class Trace(BaseModel):
    model_config = _STRICT
    conversation: Conversation
    turns: list[Turn]
    telephony: TelephonyLeg | None = None

def load_trace(path: str | Path) -> Trace:
    return Trace.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
