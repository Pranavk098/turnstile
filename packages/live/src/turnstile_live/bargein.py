"""Interruption-heavy live loop (Phase 4): full acoustic calls with a caller
who actually barges in, measuring D7 on real Piper audio at volume.

Per turn the caller text is synthesized (Piper, local) and STT'd (local
Whisper in the paid run, fakes in tests), the policy decides (capped LLM
live, mock/fake in tests), mock tools respond, and the reply is synthesized
(Piper, local) with engine-measured char/audio accounting. When the caller
(caller.ImpatientCaller, seeded) barges in mid-playback at audio fraction f,
`chars_played = round(chars_synthesized * f)` -- the same proportional
audio<->chars attribution the harness's own PiperEngine states -- and the
next turn starts at the cut point (real overlap, the D8 union's job). Full
playback otherwise. No `len(text)` anywhere near the acoustic fields.

Stated limitation (ingest format, not this loop): the adapter gives the
playback span the tts block's full duration, so D8's span union overstates
played time on cut turns -- D8 here is a conservative lower bound. D7 is
exact: its rule reads only the char counts.

Aggregation mirrors the harness definition (d7_waste / tts_spend, CIs via
deterministic bootstrap), so the headline compares apples to apples with
the ~4% figure.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from turnstile_ingest.model import (
    IngestAsr,
    IngestCall,
    IngestLlm,
    IngestTelephony,
    IngestTool,
    IngestTts,
    IngestTurn,
)

from turnstile_live.caller import ImpatientCaller
from turnstile_live.openloop import candidates_for, tools_for

AGENT_VOICE_VERSION = "turnstile-live bargein@v1"
LLM_MODEL = "gpt-5-mini"  # must resolve in pricing/rates.yaml (openai/)

_CALL_EPOCH = datetime(2026, 9, 12, 9, 0, 0, tzinfo=timezone.utc)

TOOL_MS = 300  # mock tools report no latency; fixed stated slot (P1 convention)
TURN_TAIL_MS = 300
NEXT_TURN_GAP_MS = 500

# The interruption-heavy billing script (the proposal's "impatient caller"):
# wronged twice, demands action, only the close is polite. Four turns so up
# to three agent playbacks can be cut per call.
BARGE_SCRIPT: tuple[str, ...] = (
    "Hi, I was charged twice on my bill. This is ridiculous.",
    "No, listen — order ORD-4481, the August bill. Fix it now.",
    "Just tell me the refund amount. Now.",
    "Fine. Thanks, bye.",
)


def played_chars(synth_chars: int, fraction: float | None) -> int:
    """Played chars for an interruption fraction (None = full playback).
    Proportional audio<->chars attribution; clamped strictly below synth so
    a cut turn always reads as cut (tiny-text edge, documented)."""
    if fraction is None:
        return synth_chars
    played = round(synth_chars * fraction)
    return min(played, synth_chars - 1) if synth_chars > 1 else 0


def run_bargein_call(
    *,
    call_id: str,
    scenario: str,
    caller_texts: list[str],
    caller: ImpatientCaller,
    stt,
    tts,
    llm,
    audio_dir: str | Path,
    agent_version: str = AGENT_VOICE_VERSION,
) -> tuple[IngestCall, dict[str, Any]]:
    """Run one full acoustic call. Barge draws happen on every turn except
    the last (after the final reply the caller hangs up); a cut turn's next
    turn starts at the cut point. Returns (IngestCall, notes)."""
    if not caller_texts:
        raise ValueError("caller_texts must hold at least one turn")
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    turns: list[IngestTurn] = []
    notes: list[dict[str, Any]] = []
    cursor_ms = 0
    last = len(caller_texts) - 1
    for index, scripted in enumerate(caller_texts):
        caller_wav = audio_dir / f"{call_id}-caller-{index}.wav"
        tts.synth_to_wav(scripted, caller_wav)
        transcript, asr_seconds = stt.transcribe_wav(caller_wav)
        asr_ms = int(round(asr_seconds * 1000))
        decision = llm.decide(scenario, transcript, index, candidates_for(scenario, index))
        llm_ms = int(round(decision.latency_ms))
        tool_entries = [
            IngestTool(name=r.name, kind=r.kind, effect=r.effect, args=r.args)
            for r in tools_for(decision.decision_kind, decision.decision)
        ]
        tool_ms = TOOL_MS if tool_entries else 0
        agent_wav = audio_dir / f"{call_id}-agent-{index}.wav"
        obs = tts.synth_to_wav(decision.reply, agent_wav)
        synth_ms = int(round(obs.audio_seconds * 1000))
        fraction = caller.maybe_barge_in() if index < last else None
        played = played_chars(obs.chars_synthesized, fraction)
        played_ms = int(round(obs.audio_seconds * 1000 * fraction)) if fraction is not None else synth_ms
        llm_start = cursor_ms + asr_ms
        tts_start = llm_start + llm_ms + tool_ms
        turn_end = tts_start + synth_ms + TURN_TAIL_MS
        turns.append(IngestTurn(
            start_ms=cursor_ms, end_ms=turn_end,
            barge_in=fraction is not None,
            asr=IngestAsr(transcript=transcript, start_ms=cursor_ms, duration_ms=asr_ms),
            llm=IngestLlm(
                model=LLM_MODEL, input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                decision_kind=decision.decision_kind, decision=decision.decision,
                output_text=decision.reply,
                start_ms=llm_start, duration_ms=llm_ms,
                decision_candidates=[decision.decision],
            ),
            tts=IngestTts(
                text=decision.reply, start_ms=tts_start, duration_ms=synth_ms,
                chars_synthesized=obs.chars_synthesized, chars_played=played,
            ),
            tools=tool_entries,
        ))
        notes.append({
            "scripted": scripted, "heard": transcript,
            "decision": decision.decision, "llm_fallback": decision.fallback,
            "barge_fraction": fraction, "barged": fraction is not None,
            "synth_chars": obs.chars_synthesized, "played_chars": played,
            "in_tok": decision.input_tokens, "out_tok": decision.output_tokens,
        })
        cursor_ms = tts_start + played_ms + (0 if fraction is not None else NEXT_TURN_GAP_MS)
    call_end_ms = turns[-1].end_ms
    call = IngestCall(
        id=call_id, scenario=scenario,
        started=_CALL_EPOCH,
        ended=_CALL_EPOCH + timedelta(milliseconds=call_end_ms),
        end_reason="caller_hangup", agent_version=agent_version,
        telephony=IngestTelephony(billable_seconds=(call_end_ms + 999) // 1000),
        turns=turns,
    )
    return call, {"agent_version": agent_version, "turns": notes}


def score_call(call_dict: dict[str, Any], rates, baselines) -> dict[str, Any]:
    """Price/adjudicate/detect one emitted call; return its D7/telemetry
    accounting. Heavy imports stay inside (module import stays light)."""
    from turnstile_detectors import detect
    from turnstile_ingest.adapter import load
    from turnstile_pricing import price_trace
    from turnstile_verdict import adjudicate

    priced = price_trace(load(call_dict, rates), rates)
    verdict = adjudicate(priced)
    findings = detect(priced, verdict, baselines)
    d7 = [f.waste_usd for f in findings if f.class_id == 7]
    d6 = [f.waste_usd for f in findings if f.class_id == 6]
    d8 = [f.waste_usd for f in findings if f.class_id == 8]
    tts_spend = sum(
        priced.span_costs.get(tts.span_id, 0.0)
        for turn in priced.trace.turns for tts in turn.tts)
    return {
        "verdict": verdict.label.value,
        "conv_cost": priced.conv_cost,
        "d7_waste": sum(d7), "d6_waste": sum(d6), "d8_waste": sum(d8),
        "n_d7": len(d7), "n_d6": len(d6), "n_d8": len(d8),
        "tts_spend": tts_spend,
        "n_barged": sum(1 for t in call_dict["turns"] if t.get("barge_in")),
    }


def d7_share_of_tts_spend(
    per_call: list[tuple[float, float]], seed: int = 0,
    n_resamples: int = 10000,
) -> tuple[float, float, float]:
    """D7 headline mirroring the harness: sum(waste)/sum(tts spend), with a
    deterministic ratio-bootstrap CI (resample calls, ratio per resample).
    Empty -> (0.0, 0.0, 0.0)."""
    if not per_call:
        return (0.0, 0.0, 0.0)
    waste = sum(w for w, _s in per_call)
    spend = sum(s for _w, s in per_call)
    share = waste / spend if spend > 0 else 0.0
    rng = random.Random(seed)
    n = len(per_call)
    ratios = []
    for _ in range(n_resamples):
        sample = [per_call[rng.randrange(n)] for _ in range(n)]
        sample_spend = sum(s for _w, s in sample)
        ratios.append(
            sum(w for w, _s in sample) / sample_spend if sample_spend > 0 else 0.0)
    ratios.sort()
    lo = ratios[int(0.025 * n_resamples)]
    hi = ratios[int(0.975 * n_resamples)]
    return (share, lo, hi)


def aggregate_sweep(
    cells: dict[str, list[tuple[float, float]]], seed: int = 0
) -> dict[str, dict[str, Any]]:
    """Collapse per-level (waste, spend) lists to the sweep table. n_barged
    counts calls with D7 waste (>0) -- the observable barge footprint."""
    table: dict[str, dict[str, Any]] = {}
    for level, per_call in cells.items():
        share, lo, hi = d7_share_of_tts_spend(per_call, seed=seed)
        table[level] = {
            "n_calls": len(per_call),
            "n_barged": sum(1 for w, _s in per_call if w > 0),
            "d7_share": share,
            "d7_share_ci95": [lo, hi],
            "d7_waste_usd": sum(w for w, _s in per_call),
            "tts_spend_usd": sum(s for _w, s in per_call),
        }
    return table
