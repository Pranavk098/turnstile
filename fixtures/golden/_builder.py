"""Ergonomic, valid-by-construction builders for golden fixtures.
Run a builder function and json.dump its .model_dump(by_alias=True) to disk."""
from __future__ import annotations
from turnstile_schema import (
    Trace, Conversation, Turn, LlmDecide, ToolCall, TtsSynthesize,
    AudioPlayback, AsrTranscribe, ContextAssemble, TelephonyLeg,
)

def conv(cid, scenario, end_reason, start="2026-08-30T00:00:00Z",
         end="2026-08-30T00:02:00Z", agent_version="agent@abc123"):
    return Conversation(conversation_id=cid, agent_version=agent_version,
                        scenario_id=scenario, started_at=start, ended_at=end,
                        end_reason=end_reason)

def _ms(seconds):
    """Convert seconds to whole milliseconds, matching OTel span duration units."""
    return round(seconds * 1000)

def stack(cursor, fn, **kwargs):
    """Call fn(start=cursor, **kwargs); return (span, cursor advanced by span.duration_ms).
    Lays spans back-to-back with no gap -- use for the sequential (non-overlap) case.
    For deliberate overlap or silence, pass an explicit `start=` and advance the
    cursor by hand instead of using this helper."""
    span = fn(start=cursor, **kwargs)
    return span, cursor + span.duration_ms

def llm(span_id, model, kind, chosen, candidates, out_text,
        in_tok, out_tok, latency=500, cache_read=0, system="openai", retry_of=None,
        start=0, dur=None):
    d = {
        "span_id": span_id,
        "turnstile.start_offset_ms": start,
        "turnstile.duration_ms": dur if dur is not None else latency,
        "gen_ai.system": system, "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": in_tok, "gen_ai.usage.output_tokens": out_tok,
        "turnstile.cache_read_tokens": cache_read, "turnstile.decision_kind": kind,
        "turnstile.decision_chosen": chosen, "turnstile.decision_candidates": candidates,
        "turnstile.output_text": out_text, "turnstile.latency_ms": latency}
    if retry_of:
        d["turnstile.retry_of"] = retry_of
    return LlmDecide.model_validate(d)

def tts(span_id, text, chars, secs, system="piper", start=0, dur=None):
    return TtsSynthesize.model_validate({
        "span_id": span_id,
        "turnstile.start_offset_ms": start,
        "turnstile.duration_ms": dur if dur is not None else _ms(secs),
        "gen_ai.system": system,
        "turnstile.chars_synthesized": chars,
        "turnstile.audio_seconds_generated": secs, "turnstile.text": text})

def playback(span_id, chars, secs, truncated_by=None, start=0, dur=None):
    d = {"span_id": span_id,
         "turnstile.start_offset_ms": start,
         "turnstile.duration_ms": dur if dur is not None else _ms(secs),
         "turnstile.chars_played": chars,
         "turnstile.audio_seconds_played": secs}
    if truncated_by:
        d["turnstile.truncated_by"] = truncated_by
    return AudioPlayback.model_validate(d)

def tool(span_id, name, args_hash, kind, result_hash="sha256:r", latency=300,
         start=0, dur=None, tool_status="ok", effect="none"):
    return ToolCall.model_validate({
        "span_id": span_id,
        "turnstile.start_offset_ms": start,
        "turnstile.duration_ms": dur if dur is not None else latency,
        "turnstile.tool_name": name,
        "turnstile.args_hash": args_hash, "turnstile.args_json": "{}",
        "turnstile.result_hash": result_hash, "turnstile.latency_ms": latency,
        "turnstile.tool_kind": kind,
        "turnstile.tool_status": tool_status, "turnstile.effect": effect})

def asr(span_id, transcript, audio_seconds=2.0, is_streaming=False,
        confidence=0.95, system="deepgram", model="nova-3", start=0, dur=None):
    return AsrTranscribe.model_validate({
        "span_id": span_id,
        "turnstile.start_offset_ms": start,
        "turnstile.duration_ms": dur if dur is not None else _ms(audio_seconds),
        "gen_ai.system": system,
        "gen_ai.request.model": model,
        "turnstile.audio_seconds": audio_seconds,
        "turnstile.is_streaming": is_streaming,
        "turnstile.transcript": transcript,
        "turnstile.confidence": confidence})

def context(span_id, context_tokens, history_tokens, system_tokens,
            retrieved_tokens=0, retrieved_doc_ids=None, pruning_strategy="none",
            start=0, dur=None):
    return ContextAssemble.model_validate({
        "span_id": span_id,
        "turnstile.start_offset_ms": start,
        "turnstile.duration_ms": dur if dur is not None else 80,
        "turnstile.context_tokens": context_tokens,
        "turnstile.history_tokens": history_tokens,
        "turnstile.system_tokens": system_tokens,
        "turnstile.retrieved_tokens": retrieved_tokens,
        "turnstile.retrieved_doc_ids": retrieved_doc_ids or [],
        "turnstile.pruning_strategy": pruning_strategy})

def leg(billable_seconds, provider="twilio", direction="inbound", start=0, dur=None):
    return TelephonyLeg.model_validate({
        "span_id": "leg",
        "turnstile.start_offset_ms": start,
        "turnstile.duration_ms": dur if dur is not None else _ms(billable_seconds),
        "turnstile.provider": provider,
        "turnstile.direction": direction,
        "turnstile.billable_seconds": billable_seconds})

def dump(trace: Trace, path):
    import json
    path.write_text(json.dumps(trace.model_dump(by_alias=True, mode="json"),
                               indent=2), encoding="utf-8")
