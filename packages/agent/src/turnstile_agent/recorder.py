"""TraceRecorder -- the ergonomic recorder a running voice agent wraps its
pipeline with (PRD Sec.3, schema v1.1 amendment). Produces two things per
recorded stage:

  1. A real OpenTelemetry span (via opentelemetry-sdk), carrying the
     ``gen_ai.*`` / ``turnstile.*`` attributes -- this is the live
     instrumentation signal a collector would see.
  2. The corresponding ``turnstile_schema`` span model, accumulated into a
     ``Trace`` that ``finalize()`` returns and that validates against the
     frozen schema.

Timing model (post-G1: concurrency-expressible)
-----------------------------------------------
``start_offset_ms``/``duration_ms`` (PRD Sec.3.2, base ``Span``) are derived
entirely from the injected ``clock`` callable (default ``time.monotonic``),
never from wall-clock ``datetime``, so tests can drive a fake clock and get
deterministic offsets. Each ``record_*`` call reads the clock exactly once
(the stage's end); its *start* is resolved from the timing arguments:

  * no timing argument   -- the stage starts where the turn's cursor is
    (the previous stage's end): contiguous, the common synchronous-pipeline
    case, unchanged from the pre-G1 recorder;
  * ``at_ms=X``          -- the stage starts at absolute offset X from the
    conversation start. MAY overlap any previously recorded span;
  * ``into_previous_ms=D`` -- the stage starts D ms into the start of the
    last span recorded in this turn. ``D < prev.duration_ms`` expresses
    overlap (e.g. TTS streaming during LLM decode); ``D == prev.duration_ms``
    is exactly the contiguous default, made explicit.

A negative resulting duration (claimed start after the clock read) raises
``ValueError`` -- the recorder never clamps a caller bug into fake data.

Turn lifetime model (post-G1: independent lifetimes)
----------------------------------------------------
Turns are objects with an explicit open/close lifetime, NOT strictly-nested
``with`` blocks: ``turn = rec.start_turn(i, speaker_first)`` opens the turn
(one clock read: its ``wall_start_ms``, which also seeds the cursor), and
``turn.close()`` ends it (one clock read: ``wall_end_ms``). A later turn may
therefore be OPENED -- and its spans recorded -- before an earlier turn is
closed or even fully recorded, which is exactly the live flow when a caller
barge-ins mid-playback (VAD fires while the previous turn's audio is still
streaming). This is what makes cross-turn overlap ("shape B", golden fixture
``19_edge_40_turn``) and TTS-during-LLM (``docs/GATES.md`` G1) expressible.
``finalize()`` orders turns by ``turn_index`` regardless of close order and
refuses to run while any turn is still open. A turn whose pipeline stage
raised can be dropped with ``turn.abandon(exc)`` -- it contributes no Turn
to the trace.

``conversation.started_at``/``ended_at`` are real wall-clock ``datetime``
values (the monotonic clock has no calendar meaning); only the millisecond
*offsets* on spans are clock-derived.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Tracer, TracerProvider

from turnstile_schema import SCHEMA_VERSION
from turnstile_schema.enums import (
    Direction,
    EndReason,
    Effect,
    PruningStrategy,
    SpeakerFirst,
    ToolKind,
    ToolStatus,
)
from turnstile_schema.spans import (
    AsrTranscribe,
    AudioPlayback,
    ContextAssemble,
    LlmDecide,
    TelephonyLeg,
    ToolCall,
    TtsSynthesize,
)
from turnstile_schema.trace import Conversation, Trace, Turn

_TRACER_NAME = "turnstile_otel"


def _hash_json(payload: Any) -> str:
    """sha256 of a normalized JSON encoding (sorted keys, lowercased strings)."""
    normalized = _normalize(payload)
    encoded = json.dumps(normalized, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        return {str(k).lower(): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def _clean_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """OTel attribute values must be non-None primitives/sequences; enums are
    unwrapped to their `.value`."""
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if value is None:
            continue
        if hasattr(value, "value") and not isinstance(value, (list, tuple)):
            value = value.value
        out[key] = value
    return out


class TurnRecorder:
    """One turn's recording state. Opened by ``TraceRecorder.start_turn``,
    ended by ``close()`` (kept) or dropped by ``abandon()`` (contributes
    nothing to the trace). Turns are independent-lifetime objects: turn N+1
    may be opened, and may record spans, before turn N is closed (G1)."""

    def __init__(
        self,
        parent: "TraceRecorder",
        turn_index: int,
        speaker_first: SpeakerFirst,
        barge_in: bool,
    ) -> None:
        self._parent = parent
        self.turn_index = turn_index
        self.speaker_first = speaker_first
        self.barge_in = barge_in
        self._wall_start_ms: int = parent._now_ms()
        self._cursor_ms: int = self._wall_start_ms
        self._closed = False
        self._abandoned = False
        self._last_span: Any = None  # last span recorded in this turn (any kind)

        self.asr: list[AsrTranscribe] = []
        self.context: ContextAssemble | None = None
        self.llm: list[LlmDecide] = []
        self.tools: list[ToolCall] = []
        self.tts: list[TtsSynthesize] = []
        self.playback: list[AudioPlayback] = []

        self._span = self._parent._tracer.start_span(
            "turn",
            context=self._parent._conversation_context,
            attributes=_clean_attrs(
                {
                    "turnstile.turn_index": self.turn_index,
                    "turnstile.speaker_first": self.speaker_first,
                }
            ),
        )
        self._span_context = otel_trace.set_span_in_context(self._span)

    # -- lifetime -----------------------------------------------------------

    def _ensure_open(self, action: str) -> None:
        if self._abandoned:
            raise RuntimeError(f"turn {self.turn_index} is abandoned -- cannot {action}")
        if self._closed:
            raise RuntimeError(f"turn {self.turn_index} is closed -- cannot {action}")

    def close(self) -> None:
        """End the turn: one clock read for ``wall_end_ms``, close the OTel
        span, and register the finished ``Turn`` with the recorder."""
        self._ensure_open("close")
        self._closed = True
        self._wall_end_ms = self._parent._now_ms()
        self._span.set_attribute("turnstile.barge_in", self.barge_in)
        self._span.end()
        self._parent._register_closed_turn(
            Turn(
                turn_index=self.turn_index,
                speaker_first=self.speaker_first,
                wall_start_ms=self._wall_start_ms,
                wall_end_ms=self._wall_end_ms,
                barge_in=self.barge_in,
                asr=self.asr,
                context=self.context,
                llm=self.llm,
                tools=self.tools,
                tts=self.tts,
                playback=self.playback,
            )
        )

    def abandon(self, exc: BaseException | None = None) -> None:
        """Drop the turn entirely (e.g. a pipeline stage raised and the turn
        cannot be completed): it contributes no ``Turn`` to the trace. If
        ``exc`` is given it is recorded on the OTel span, which is closed
        with an ERROR status."""
        self._ensure_open("abandon")
        self._abandoned = True
        if exc is not None:
            self._span.record_exception(exc)
            self._span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR))
        self._span.end()
        self._parent._register_abandoned_turn(self.turn_index)

    def mark_barge_in(self, value: bool = True) -> None:
        """Flip barge_in after the fact (e.g. detected mid-playback)."""
        self.barge_in = value

    # -- internal timing / emission -----------------------------------------

    def _resolve_start(self, at_ms: int | None, into_previous_ms: int | None) -> int:
        if at_ms is not None and into_previous_ms is not None:
            raise ValueError("at_ms and into_previous_ms are mutually exclusive")
        if at_ms is not None:
            if at_ms < 0:
                raise ValueError(f"at_ms must be >= 0, got {at_ms}")
            return at_ms
        if into_previous_ms is not None:
            if into_previous_ms < 0:
                raise ValueError(f"into_previous_ms must be >= 0, got {into_previous_ms}")
            if self._last_span is None:
                raise ValueError(
                    "into_previous_ms requires a previously recorded span in this turn; "
                    "use at_ms for the turn's first span"
                )
            return self._last_span.start_offset_ms + into_previous_ms
        return self._cursor_ms

    def _advance(self, *, at_ms: int | None = None, into_previous_ms: int | None = None) -> tuple[int, int]:
        """Resolve the stage's start (contiguous by default, overlappable via
        ``at_ms``/``into_previous_ms``), read the clock once for its end, and
        move the cursor to that end."""
        self._ensure_open("record a span")
        start = self._resolve_start(at_ms, into_previous_ms)
        now = self._parent._now_ms()
        duration = now - start
        if duration < 0:
            raise ValueError(
                f"stage end {now}ms precedes claimed start {start}ms "
                f"(negative duration {duration}ms) -- caller bug, refusing to record"
            )
        self._cursor_ms = now
        return start, duration

    def _emit(self, name: str, attrs: dict[str, Any]) -> None:
        self._parent._emit_span(name, attrs, context=self._span_context)

    # -- stage recorders -----------------------------------------------------

    def record_asr(
        self,
        *,
        gen_ai_system: str,
        gen_ai_request_model: str,
        audio_seconds: float,
        is_streaming: bool,
        transcript: str,
        confidence: float,
        at_ms: int | None = None,
        into_previous_ms: int | None = None,
    ) -> AsrTranscribe:
        start, duration = self._advance(at_ms=at_ms, into_previous_ms=into_previous_ms)
        span = AsrTranscribe(
            span_id=self._parent._next_span_id("asr"),
            start_offset_ms=start,
            duration_ms=duration,
            gen_ai_system=gen_ai_system,
            gen_ai_request_model=gen_ai_request_model,
            audio_seconds=audio_seconds,
            is_streaming=is_streaming,
            transcript=transcript,
            confidence=confidence,
        )
        self.asr.append(span)
        self._last_span = span
        self._emit(
            "asr.transcribe",
            {
                "turnstile.start_offset_ms": start,
                "turnstile.duration_ms": duration,
                "gen_ai.system": gen_ai_system,
                "gen_ai.request.model": gen_ai_request_model,
                "turnstile.audio_seconds": audio_seconds,
                "turnstile.is_streaming": is_streaming,
                "turnstile.transcript": transcript,
                "turnstile.confidence": confidence,
            },
        )
        return span

    def set_context(
        self,
        *,
        context_tokens: int,
        history_tokens: int,
        system_tokens: int,
        retrieved_tokens: int,
        retrieved_doc_ids: list[str],
        pruning_strategy: PruningStrategy | str,
        at_ms: int | None = None,
        into_previous_ms: int | None = None,
    ) -> ContextAssemble:
        start, duration = self._advance(at_ms=at_ms, into_previous_ms=into_previous_ms)
        pruning_strategy = PruningStrategy(pruning_strategy)
        span = ContextAssemble(
            span_id=self._parent._next_span_id("ctx"),
            start_offset_ms=start,
            duration_ms=duration,
            context_tokens=context_tokens,
            history_tokens=history_tokens,
            system_tokens=system_tokens,
            retrieved_tokens=retrieved_tokens,
            retrieved_doc_ids=retrieved_doc_ids,
            pruning_strategy=pruning_strategy,
        )
        self.context = span
        self._last_span = span
        self._emit(
            "context.assemble",
            {
                "turnstile.start_offset_ms": start,
                "turnstile.duration_ms": duration,
                "turnstile.context_tokens": context_tokens,
                "turnstile.history_tokens": history_tokens,
                "turnstile.system_tokens": system_tokens,
                "turnstile.retrieved_tokens": retrieved_tokens,
                "turnstile.retrieved_doc_ids": list(retrieved_doc_ids),
                "turnstile.pruning_strategy": pruning_strategy,
            },
        )
        return span

    def record_llm(
        self,
        *,
        gen_ai_system: str,
        gen_ai_request_model: str,
        input_tokens: int,
        output_tokens: int,
        decision_kind,
        decision_chosen: str,
        decision_candidates: list[str],
        output_text: str,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        retry_of: str | None = None,
        latency_ms: int | None = None,
        at_ms: int | None = None,
        into_previous_ms: int | None = None,
    ) -> LlmDecide:
        start, duration = self._advance(at_ms=at_ms, into_previous_ms=into_previous_ms)
        latency = duration if latency_ms is None else latency_ms
        span = LlmDecide(
            span_id=self._parent._next_span_id("llm"),
            start_offset_ms=start,
            duration_ms=duration,
            gen_ai_system=gen_ai_system,
            gen_ai_request_model=gen_ai_request_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            decision_kind=decision_kind,
            decision_chosen=decision_chosen,
            decision_candidates=decision_candidates,
            output_text=output_text,
            latency_ms=latency,
            retry_of=retry_of,
        )
        self.llm.append(span)
        self._last_span = span
        self._emit(
            "llm.decide",
            {
                "turnstile.start_offset_ms": start,
                "turnstile.duration_ms": duration,
                "gen_ai.system": gen_ai_system,
                "gen_ai.request.model": gen_ai_request_model,
                "gen_ai.usage.input_tokens": input_tokens,
                "gen_ai.usage.output_tokens": output_tokens,
                "turnstile.cache_read_tokens": cache_read_tokens,
                "turnstile.cache_write_tokens": cache_write_tokens,
                "turnstile.reasoning_tokens": reasoning_tokens,
                "turnstile.decision_kind": span.decision_kind,
                "turnstile.decision_chosen": decision_chosen,
                "turnstile.decision_candidates": list(decision_candidates),
                "turnstile.output_text": output_text,
                "turnstile.latency_ms": latency,
                "turnstile.retry_of": retry_of,
            },
        )
        return span

    def record_tool(
        self,
        *,
        tool_name: str,
        tool_kind: ToolKind | str,
        tool_status: ToolStatus | str = ToolStatus.ok,
        effect: Effect | str = Effect.none,
        args: dict | None = None,
        result: Any = None,
        args_json: str | None = None,
        result_hash: str | None = None,
        cost_usd: float = 0.0,
        latency_ms: int | None = None,
        at_ms: int | None = None,
        into_previous_ms: int | None = None,
    ) -> ToolCall:
        start, duration = self._advance(at_ms=at_ms, into_previous_ms=into_previous_ms)
        args = args or {}
        latency = duration if latency_ms is None else latency_ms
        args_hash = _hash_json(args)
        args_json_val = (
            args_json if args_json is not None else json.dumps(args, sort_keys=True, default=str)
        )
        result_hash_val = result_hash if result_hash is not None else _hash_json(result)

        # Constructing ToolCall runs the schema's model_validator(mode="after")
        # (tool_kind x tool_status x effect, schema v1.1 amendment T3) -- an
        # illegal combination raises pydantic.ValidationError here, the shim
        # never bypasses that check.
        span = ToolCall(
            span_id=self._parent._next_span_id("tool"),
            start_offset_ms=start,
            duration_ms=duration,
            tool_name=tool_name,
            args_hash=args_hash,
            args_json=args_json_val,
            result_hash=result_hash_val,
            latency_ms=latency,
            cost_usd=cost_usd,
            tool_kind=tool_kind,
            tool_status=tool_status,
            effect=effect,
        )
        self.tools.append(span)
        self._last_span = span
        self._emit(
            "tool.call",
            {
                "turnstile.start_offset_ms": start,
                "turnstile.duration_ms": duration,
                "turnstile.tool_name": tool_name,
                "turnstile.args_hash": args_hash,
                "turnstile.result_hash": result_hash_val,
                "turnstile.latency_ms": latency,
                "turnstile.cost_usd": cost_usd,
                "turnstile.tool_kind": span.tool_kind,
                "turnstile.tool_status": span.tool_status,
                "turnstile.effect": span.effect,
            },
        )
        return span

    def record_tts(
        self,
        *,
        gen_ai_system: str,
        text: str,
        audio_seconds_generated: float,
        chars_synthesized: int,
        at_ms: int | None = None,
        into_previous_ms: int | None = None,
    ) -> TtsSynthesize:
        # chars_synthesized is required, not derived from len(text): it must
        # be the GENERATED/billed character count, never the intended text
        # length (GATES.md G2) -- a len(text) fallback here would silently
        # bill intended text instead of what was actually synthesized.
        start, duration = self._advance(at_ms=at_ms, into_previous_ms=into_previous_ms)
        chars = chars_synthesized
        span = TtsSynthesize(
            span_id=self._parent._next_span_id("tts"),
            start_offset_ms=start,
            duration_ms=duration,
            gen_ai_system=gen_ai_system,
            chars_synthesized=chars,
            audio_seconds_generated=audio_seconds_generated,
            text=text,
        )
        self.tts.append(span)
        self._last_span = span
        self._emit(
            "tts.synthesize",
            {
                "turnstile.start_offset_ms": start,
                "turnstile.duration_ms": duration,
                "gen_ai.system": gen_ai_system,
                "turnstile.chars_synthesized": chars,
                "turnstile.audio_seconds_generated": audio_seconds_generated,
                "turnstile.text": text,
            },
        )
        return span

    def record_playback(
        self,
        *,
        chars_played: int,
        audio_seconds_played: float,
        truncated_by: str | None = None,
        at_ms: int | None = None,
        into_previous_ms: int | None = None,
    ) -> AudioPlayback:
        start, duration = self._advance(at_ms=at_ms, into_previous_ms=into_previous_ms)
        span = AudioPlayback(
            span_id=self._parent._next_span_id("playback"),
            start_offset_ms=start,
            duration_ms=duration,
            chars_played=chars_played,
            audio_seconds_played=audio_seconds_played,
            truncated_by=truncated_by,
        )
        self.playback.append(span)
        self._last_span = span
        self._emit(
            "audio.playback",
            {
                "turnstile.start_offset_ms": start,
                "turnstile.duration_ms": duration,
                "turnstile.chars_played": chars_played,
                "turnstile.audio_seconds_played": audio_seconds_played,
                "turnstile.truncated_by": truncated_by,
            },
        )
        return span


class TraceRecorder:
    """Wrap a running voice agent's pipeline to emit schema-v1.1-valid
    Turnstile traces (PRD Sec.3) plus real OTel spans for each recorded
    stage.

    Usage::

        rec = TraceRecorder("conv-1", "agent@abc123", "order_status")
        turn0 = rec.start_turn(0, "caller")
        turn0.record_asr(...)
        turn0.record_llm(...)                       # contiguous by default
        tts = turn0.record_tts(..., into_previous_ms=llm.duration_ms // 2)
        turn0.close()                               # or keep it open: turn
        turn1 = rec.start_turn(1, "agent")          # lifetimes are independent
        turn1.record_llm(...)                       # may overlap turn0's spans
        turn0.close()
        rec.record_telephony("twilio", "inbound", billable_seconds=12)
        trace = rec.finalize("caller_hangup")
    """

    def __init__(
        self,
        conversation_id: str,
        agent_version: str,
        scenario_id: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        tracer_provider: TracerProvider | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.agent_version = agent_version
        self.scenario_id = scenario_id
        self._clock = clock
        self._t0 = clock()
        self._started_at = datetime.now(timezone.utc)
        self._turns_by_index: dict[int, Turn] = {}
        self._open_turns: dict[int, TurnRecorder] = {}
        self._span_counter = itertools.count()
        self._telephony_args: dict | None = None
        self._finalized = False

        self._tracer_provider = tracer_provider or otel_trace.get_tracer_provider()
        self._tracer: Tracer = self._tracer_provider.get_tracer(_TRACER_NAME)

        self._conversation_span = self._tracer.start_span(
            "conversation",
            attributes=_clean_attrs(
                {
                    "turnstile.conversation_id": conversation_id,
                    "turnstile.agent_version": agent_version,
                    "turnstile.scenario_id": scenario_id,
                    "turnstile.schema_version": SCHEMA_VERSION,
                }
            ),
        )
        self._conversation_context = otel_trace.set_span_in_context(self._conversation_span)

    # -- internal --------------------------------------------------------

    def _now_ms(self) -> int:
        return round((self._clock() - self._t0) * 1000)

    def _next_span_id(self, kind: str) -> str:
        return f"{kind}_{next(self._span_counter)}"

    def _emit_span(self, name: str, attrs: dict[str, Any], *, context) -> None:
        span = self._tracer.start_span(name, context=context, attributes=_clean_attrs(attrs))
        span.end()

    def _register_closed_turn(self, turn: Turn) -> None:
        self._turns_by_index[turn.turn_index] = turn
        self._open_turns.pop(turn.turn_index, None)

    def _register_abandoned_turn(self, turn_index: int) -> None:
        self._open_turns.pop(turn_index, None)

    # -- public API --------------------------------------------------------

    def start_turn(
        self, turn_index: int, speaker_first: SpeakerFirst | str, *, barge_in: bool = False
    ) -> TurnRecorder:
        """Open a turn (one clock read: ``wall_start_ms``, which seeds the
        turn's cursor). The returned object has an independent lifetime:
        close it with ``.close()`` when the turn ends -- other turns may be
        opened and recorded in the meantime (G1)."""
        if self._finalized:
            raise RuntimeError("TraceRecorder.finalize() already called")
        if turn_index in self._turns_by_index or turn_index in self._open_turns:
            raise ValueError(f"turn {turn_index} already opened -- turn indexes must be unique")
        turn = TurnRecorder(self, turn_index, SpeakerFirst(speaker_first), barge_in)
        self._open_turns[turn_index] = turn
        return turn

    def record_telephony(
        self, provider: str, direction: Direction | str, billable_seconds: int
    ) -> None:
        """telephony.leg spans the whole conversation (sibling of the root),
        so its span_id/duration are only known once the call ends -- resolved
        in ``finalize()``."""
        self._telephony_args = {
            "provider": provider,
            "direction": Direction(direction),
            "billable_seconds": billable_seconds,
        }

    def finalize(self, end_reason: EndReason | str) -> Trace:
        if self._finalized:
            raise RuntimeError("TraceRecorder.finalize() already called")
        if self._open_turns:
            still_open = ", ".join(f"turn {i}" for i in sorted(self._open_turns))
            raise RuntimeError(
                f"{len(self._open_turns)} turn(s) still open: {still_open} -- "
                "close() or abandon() them before finalize()"
            )
        self._finalized = True

        end_reason = EndReason(end_reason)
        ended_at = datetime.now(timezone.utc)
        total_ms = self._now_ms()

        telephony: TelephonyLeg | None = None
        if self._telephony_args is not None:
            telephony = TelephonyLeg(
                span_id=self._next_span_id("telephony"),
                start_offset_ms=0,
                duration_ms=total_ms,
                provider=self._telephony_args["provider"],
                direction=self._telephony_args["direction"],
                billable_seconds=self._telephony_args["billable_seconds"],
            )
            self._emit_span(
                "telephony.leg",
                {
                    "turnstile.start_offset_ms": telephony.start_offset_ms,
                    "turnstile.duration_ms": telephony.duration_ms,
                    "turnstile.provider": telephony.provider,
                    "turnstile.direction": telephony.direction,
                    "turnstile.billable_seconds": telephony.billable_seconds,
                },
                context=None,
            )

        self._conversation_span.set_attribute("turnstile.end_reason", end_reason.value)
        self._conversation_span.end()

        conversation = Conversation(
            conversation_id=self.conversation_id,
            agent_version=self.agent_version,
            scenario_id=self.scenario_id,
            started_at=self._started_at,
            ended_at=ended_at,
            end_reason=end_reason,
        )
        turns = [self._turns_by_index[i] for i in sorted(self._turns_by_index)]
        return Trace(conversation=conversation, turns=turns, telephony=telephony)
