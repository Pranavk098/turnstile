"""Map the external ingest format to a schema-valid v1.1 ``Trace``.

``load(obj) -> Trace``: validate ``obj`` against the ingest Pydantic model
(field-pointed errors on malformed input), check every rate key resolves
against ``pricing/rates.yaml`` (a money-affecting miss must fail here, not as
a ``KeyError`` deep in pricing), then build the ``Trace``.

Honest-omission rules (see docs/INGEST.md § "what the adapter cannot map"):

* A ``tts`` block WITHOUT both G2 acoustic fields produces NO tts/playback
  spans. G2 (docs/GATES.md) forbids ``len(text)`` as ``chars_synthesized``,
  so there is no honest span to emit. The pipeline (``pipeline.py``) reports
  D6/D7/D8 ABSENT for such calls -- never zero, never faked.
* A ``tts`` block WITH only one of the two fields emits only that side's
  span (a known generated-char count is real billable TTS cost even when the
  played count is unknown, and vice versa carries no cost claim).
* ``llm.tool_calls`` is informational bookkeeping from the platform log and
  is NOT mapped (v1.1 carries no llm->tool link; the turn's ``tools`` list
  is authoritative).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from turnstile_schema import RateTable, Trace, load_rates
from turnstile_ingest.model import IngestCall, IngestTool, IngestTurn

_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_RATES_PATH = _REPO_ROOT / "pricing" / "rates.yaml"


class IngestError(ValueError):
    """Malformed ingest input. The message always names the offending field
    path (e.g. ``turns[1].llm.input_tokens``), never just "invalid input"."""


def _format_loc(loc: tuple) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        elif not out:
            out = str(part)
        else:
            out += f".{part}"
    return out


def _format_pydantic_error(exc: ValidationError, prefix: str = "") -> str:
    return "; ".join(
        f"{prefix}{_format_loc(err['loc'])}: {err['msg']}" for err in exc.errors()
    )


def parse_call(obj: dict[str, Any] | IngestCall) -> IngestCall:
    """Validate ``obj`` as one ingest call. Raises ``IngestError`` naming
    the bad field path on malformed input."""
    if isinstance(obj, IngestCall):
        return obj
    try:
        return IngestCall.model_validate(obj)
    except ValidationError as exc:
        raise IngestError(f"invalid ingest call -- {_format_pydantic_error(exc)}") from exc


def _require_rate_key(mapping: dict, key: str, field_path: str, what: str) -> None:
    if key not in mapping:
        known = ", ".join(sorted(mapping))
        raise IngestError(
            f"{field_path}: {what} {key!r} is not in pricing/rates.yaml "
            f"(known: {known})"
        )


def _hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _build_tool_span(call_id: str, turn_index: int, seq: int, tool: IngestTool, turn: IngestTurn) -> dict[str, Any]:
    start_ms = tool.start_ms if tool.start_ms is not None else turn.start_ms
    duration_ms = tool.duration_ms if tool.duration_ms is not None else 0
    args_json = json.dumps(tool.args, sort_keys=True, separators=(",", ":"))
    return {
        "span_id": f"{call_id}:t{turn_index}:tool{seq}",
        "turnstile.start_offset_ms": start_ms,
        "turnstile.duration_ms": duration_ms,
        "turnstile.tool_name": tool.name,
        "turnstile.args_hash": _hash(tool.args),
        "turnstile.args_json": args_json,
        "turnstile.result_hash": _hash(tool.result),
        "turnstile.latency_ms": duration_ms,
        "turnstile.cost_usd": tool.cost_usd,
        "turnstile.tool_kind": tool.kind.value,
        "turnstile.tool_status": tool.status.value,
        "turnstile.effect": tool.effect.value,
    }


def _trace_dict(call: IngestCall, rates: RateTable) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    for i, turn in enumerate(call.turns):
        asr_spans: list[dict[str, Any]] = []
        llm_spans: list[dict[str, Any]] = []
        tool_spans: list[dict[str, Any]] = []
        tts_spans: list[dict[str, Any]] = []
        playback_spans: list[dict[str, Any]] = []

        if turn.asr is not None:
            asr = turn.asr
            _require_rate_key(
                rates.asr, f"{asr.system}/{asr.model}",
                f"turns[{i}].asr.model", "ASR rate key",
            )
            asr_spans.append({
                "span_id": f"{call.id}:t{i}:asr",
                "turnstile.start_offset_ms": asr.start_ms,
                "turnstile.duration_ms": asr.duration_ms,
                "gen_ai.system": asr.system,
                "gen_ai.request.model": asr.model,
                "turnstile.audio_seconds": asr.duration_ms / 1000.0,
                "turnstile.is_streaming": asr.streaming,
                "turnstile.transcript": asr.transcript,
                "turnstile.confidence": asr.confidence,
            })

        if turn.llm is not None:
            llm = turn.llm
            _require_rate_key(
                rates.llm, f"{llm.system}/{llm.model}",
                f"turns[{i}].llm.model", "LLM rate key",
            )
            llm_spans.append({
                "span_id": f"{call.id}:t{i}:llm",
                "turnstile.start_offset_ms": llm.start_ms,
                "turnstile.duration_ms": llm.duration_ms,
                "gen_ai.system": llm.system,
                "gen_ai.request.model": llm.model,
                "gen_ai.usage.input_tokens": llm.input_tokens,
                "gen_ai.usage.output_tokens": llm.output_tokens,
                "turnstile.cache_read_tokens": llm.cache_read_tokens,
                "turnstile.cache_write_tokens": llm.cache_write_tokens,
                "turnstile.reasoning_tokens": llm.reasoning_tokens,
                "turnstile.decision_kind": llm.decision_kind.value,
                "turnstile.decision_chosen": llm.decision,
                "turnstile.decision_candidates": llm.candidates(),
                "turnstile.output_text": llm.output_text,
                "turnstile.latency_ms": llm.duration_ms,
                "turnstile.retry_of": None,
            })

        for seq, tool in enumerate(turn.tools):
            tool_spans.append(_build_tool_span(call.id, i, seq, tool, turn))

        if turn.tts is not None:
            tts = turn.tts
            _require_rate_key(rates.tts, tts.system, f"turns[{i}].tts.system", "TTS rate key")
            if tts.chars_synthesized is not None:
                tts_spans.append({
                    "span_id": f"{call.id}:t{i}:tts",
                    "turnstile.start_offset_ms": tts.start_ms,
                    "turnstile.duration_ms": tts.duration_ms,
                    "gen_ai.system": tts.system,
                    "turnstile.chars_synthesized": tts.chars_synthesized,
                    "turnstile.audio_seconds_generated": tts.duration_ms / 1000.0,
                    "turnstile.text": tts.text,
                })
            if tts.chars_played is not None:
                playback_spans.append({
                    "span_id": f"{call.id}:t{i}:play",
                    "turnstile.start_offset_ms": tts.start_ms,
                    "turnstile.duration_ms": tts.duration_ms,
                    "turnstile.chars_played": tts.chars_played,
                    "turnstile.audio_seconds_played": tts.duration_ms / 1000.0,
                    "turnstile.truncated_by": None,
                })

        turns.append({
            "turn_index": i,
            "speaker_first": turn.speaker_first.value,
            "wall_start_ms": turn.start_ms,
            "wall_end_ms": turn.end_ms,
            "barge_in": turn.barge_in,
            "vad": [],
            "asr": asr_spans,
            "context": None,
            "llm": llm_spans,
            "tools": tool_spans,
            "tts": tts_spans,
            "playback": playback_spans,
        })

    telephony = None
    if call.telephony is not None:
        tel = call.telephony
        _require_rate_key(
            rates.telephony, f"{tel.provider}/pstn_{tel.direction.value}",
            "telephony", "telephony rate key",
        )
        call_ms = int((call.ended - call.started).total_seconds() * 1000)
        telephony = {
            "span_id": f"{call.id}:leg",
            "turnstile.start_offset_ms": 0,
            "turnstile.duration_ms": max(call_ms, 0),
            "turnstile.provider": tel.provider,
            "turnstile.direction": tel.direction.value,
            "turnstile.billable_seconds": tel.billable_seconds,
        }

    return {
        "conversation": {
            "conversation_id": call.id,
            "agent_version": call.agent_version,
            "scenario_id": call.scenario,
            "started_at": call.started.isoformat(),
            "ended_at": call.ended.isoformat(),
            "end_reason": call.end_reason.value,
            "turnstile.schema_version": "1.1",
        },
        "turns": turns,
        "telephony": telephony,
    }


def load(obj: dict[str, Any] | IngestCall, rates: RateTable | None = None) -> Trace:
    """Map one ingest call object to a schema-valid v1.1 ``Trace``.

    Raises ``IngestError`` (a ``ValueError``) naming the bad field when the
    input is malformed or a model/provider has no rate-table entry. The
    existing ``price_trace`` / ``adjudicate`` / ``detect`` then run unchanged
    on the returned ``Trace``.
    """
    call = parse_call(obj)
    table = rates if rates is not None else load_rates(DEFAULT_RATES_PATH)
    try:
        return Trace.model_validate(_trace_dict(call, table))
    except ValidationError as exc:
        raise IngestError(
            f"ingest call {call.id!r} maps to an invalid Trace "
            f"(adapter bug, not input) -- {_format_pydantic_error(exc)}"
        ) from exc
