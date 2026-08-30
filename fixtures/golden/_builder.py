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

def llm(span_id, model, kind, chosen, candidates, out_text,
        in_tok, out_tok, latency=500, cache_read=0, system="openai", retry_of=None):
    d = {
        "span_id": span_id, "gen_ai.system": system, "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": in_tok, "gen_ai.usage.output_tokens": out_tok,
        "turnstile.cache_read_tokens": cache_read, "turnstile.decision_kind": kind,
        "turnstile.decision_chosen": chosen, "turnstile.decision_candidates": candidates,
        "turnstile.output_text": out_text, "turnstile.latency_ms": latency}
    if retry_of:
        d["turnstile.retry_of"] = retry_of
    return LlmDecide.model_validate(d)

def tts(span_id, text, chars, secs, system="piper"):
    return TtsSynthesize.model_validate({
        "span_id": span_id, "gen_ai.system": system,
        "turnstile.chars_synthesized": chars,
        "turnstile.audio_seconds_generated": secs, "turnstile.text": text})

def playback(span_id, chars, secs, truncated_by=None):
    d = {"span_id": span_id, "turnstile.chars_played": chars,
         "turnstile.audio_seconds_played": secs}
    if truncated_by:
        d["turnstile.truncated_by"] = truncated_by
    return AudioPlayback.model_validate(d)

def tool(span_id, name, args_hash, kind, result_hash="sha256:r", latency=300):
    return ToolCall.model_validate({
        "span_id": span_id, "turnstile.tool_name": name,
        "turnstile.args_hash": args_hash, "turnstile.args_json": "{}",
        "turnstile.result_hash": result_hash, "turnstile.latency_ms": latency,
        "turnstile.tool_kind": kind})

def asr(span_id, transcript, audio_seconds=2.0, is_streaming=False,
        confidence=0.95, system="deepgram", model="nova-2"):
    return AsrTranscribe.model_validate({
        "span_id": span_id, "gen_ai.system": system,
        "gen_ai.request.model": model,
        "turnstile.audio_seconds": audio_seconds,
        "turnstile.is_streaming": is_streaming,
        "turnstile.transcript": transcript,
        "turnstile.confidence": confidence})

def context(span_id, context_tokens, history_tokens, system_tokens,
            retrieved_tokens=0, retrieved_doc_ids=None, pruning_strategy="none"):
    return ContextAssemble.model_validate({
        "span_id": span_id,
        "turnstile.context_tokens": context_tokens,
        "turnstile.history_tokens": history_tokens,
        "turnstile.system_tokens": system_tokens,
        "turnstile.retrieved_tokens": retrieved_tokens,
        "turnstile.retrieved_doc_ids": retrieved_doc_ids or [],
        "turnstile.pruning_strategy": pruning_strategy})

def leg(billable_seconds, provider="twilio", direction="inbound"):
    return TelephonyLeg.model_validate({
        "span_id": "leg", "turnstile.provider": provider,
        "turnstile.direction": direction,
        "turnstile.billable_seconds": billable_seconds})

def dump(trace: Trace, path):
    import json
    path.write_text(json.dumps(trace.model_dump(by_alias=True, mode="json"),
                               indent=2), encoding="utf-8")
