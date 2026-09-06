"""External ingest format for Turnstile (W3-A).

A real voice-AI platform log is simpler than the internal v1.1 ``Trace``: one
call with conversation metadata and a flat list of turns, each carrying at
most one ASR / LLM / TTS observation plus the turn's tool calls. See
``docs/INGEST.md`` for the field-by-field contract and a full example.

Design notes (all load-bearing, all documented in docs/INGEST.md):

* Times are call-relative wall milliseconds (``turn.start_ms``/``end_ms``,
  span ``start_ms`` + ``duration_ms``), matching ``Trace``'s own
  ``start_offset_ms`` convention (verified against fixtures/golden).
* ``extra="forbid"`` everywhere: a misspelled field fails loudly with the
  field path, instead of being silently dropped.
* Fields the brief sketch omits but v1.1 validity requires are REQUIRED here
  rather than derived: tool ``kind`` (no honest derivation exists),
  ``llm.output_text`` (verdict + D3/D5/D6 read it; never copied from
  ``tts.text``), turn wall bounds, telephony as one conversation-level leg.
* G2 acoustic fields (``tts.chars_synthesized``/``chars_played``) are
  OPTIONAL. When absent the adapter emits no tts/playback spans (G2 forbids
  ``len(text)`` as a stand-in) and the pipeline reports D6/D7/D8 ABSENT.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from turnstile_schema.enums import (
    DecisionKind,
    Direction,
    Effect,
    EndReason,
    SpeakerFirst,
    ToolKind,
    ToolStatus,
)

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")


class IngestAsr(BaseModel):
    """One caller utterance as the platform's ASR reported it."""

    model_config = _STRICT
    transcript: str
    start_ms: int
    duration_ms: int
    model: str = "nova-3"
    system: str = "deepgram"
    confidence: float = 0.9
    streaming: bool = True


class IngestLlm(BaseModel):
    """One agent decision step. At most one per turn."""

    model_config = _STRICT
    model: str
    input_tokens: int
    output_tokens: int
    decision_kind: DecisionKind
    decision: str
    output_text: str
    start_ms: int
    duration_ms: int
    system: str = "openai"
    decision_candidates: list[str] | None = None
    tool_calls: list[str] = Field(default_factory=list)
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def candidates(self) -> list[str]:
        return self.decision_candidates if self.decision_candidates else [self.decision]


class IngestTts(BaseModel):
    """One agent spoken reply. Acoustic char counts are OPTIONAL (G2)."""

    model_config = _STRICT
    text: str
    start_ms: int
    duration_ms: int
    system: str = "piper"
    chars_synthesized: int | None = None
    chars_played: int | None = None

    def acoustic_complete(self) -> bool:
        return self.chars_synthesized is not None and self.chars_played is not None


class IngestTool(BaseModel):
    """One tool call on the turn. ``kind``/``effect`` are load-bearing for
    the verdict layer and have no honest default, so both are required."""

    model_config = _STRICT
    name: str
    kind: ToolKind
    effect: Effect
    args: dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus = ToolStatus.ok
    result: Any | None = None
    start_ms: int | None = None
    duration_ms: int | None = None
    cost_usd: float = 0.0


class IngestTelephony(BaseModel):
    """The call's single telephony leg (conversation-level: v1.1 carries one
    ``TelephonyLeg`` per trace, so per-turn telephony cannot map)."""

    model_config = _STRICT
    provider: str = "twilio"
    direction: Direction = Direction.inbound
    billable_seconds: int


class IngestTurn(BaseModel):
    """One conversational turn. Span times are call-relative wall ms."""

    model_config = _STRICT
    start_ms: int
    end_ms: int
    speaker_first: SpeakerFirst = SpeakerFirst.caller
    barge_in: bool = False
    asr: IngestAsr | None = None
    llm: IngestLlm | None = None
    tts: IngestTts | None = None
    tools: list[IngestTool] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_wall(self):
        if self.end_ms < self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) < start_ms ({self.start_ms})")
        return self


class IngestCall(BaseModel):
    """One call in the external ingest format. ``load()`` maps this to a
    schema-valid v1.1 ``Trace``."""

    model_config = _STRICT
    id: str
    scenario: str
    started: datetime
    ended: datetime
    end_reason: EndReason
    agent_version: str = "unknown"
    telephony: IngestTelephony | None = None
    turns: list[IngestTurn] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_order(self):
        if self.turns:
            for i, turn in enumerate(self.turns[1:], start=1):
                if turn.start_ms < self.turns[i - 1].start_ms:
                    raise ValueError(
                        f"turns[{i}].start_ms ({turn.start_ms}) precedes "
                        f"turns[{i - 1}].start_ms ({self.turns[i - 1].start_ms}): "
                        "turns must be in wall order"
                    )
        return self


# A file holds either one call object or {"calls": [...]} (plus optional
# "sample"/"note" bookkeeping keys, which are informational only).
IngestFile = dict[str, Any]

CALLSET_KEYS = frozenset({"calls"})
BOOKKEEPING_KEYS = frozenset({"sample", "note", "label"})

FileKind = Literal["call", "callset"]


def classify_file(obj: Any) -> FileKind | None:
    """One call object -> "call"; {"calls": [...]} / bare list -> "callset";
    anything else -> None (the CLI reports it as malformed)."""
    if isinstance(obj, list):
        return "callset"
    if isinstance(obj, dict):
        if "calls" in obj:
            return "callset"
        if "id" in obj:
            return "call"
    return None
