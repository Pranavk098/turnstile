"""Text-mode agent loop (Phase 1): scripted caller turns in, ingest call out.

One caller turn becomes one ingest turn: the caller text is recorded as the
turn's ASR, the mock policy decides, an optional mock tool runs, and the
reply is recorded as the turn's llm + tts blocks. A virtual clock lays out
fixed wall-ms slots, so the emitted call is fully deterministic.

HONESTY (load-bearing): token counts, latencies, and tool outcomes are MOCK
telemetry from fixed formulas below -- priced like any log's own telemetry by
the ingest pipeline, exactly as the synthetic corpus's tokens are. The call
is labeled ``agent_version="turnstile-live textmode@mock-1"`` so no artifact
can be mistaken for a measured production call. TTS carries text only (no G2
char counts, the typical real log), so D6/D7/D8 report ABSENT downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from turnstile_ingest.model import (
    IngestAsr,
    IngestCall,
    IngestLlm,
    IngestTelephony,
    IngestTool,
    IngestTts,
    IngestTurn,
)

from turnstile_live.policy import decide
from turnstile_live.tools import run_tool

AGENT_VERSION = "turnstile-live textmode@mock-1"
LLM_MODEL = "gpt-5-mini"  # must resolve in pricing/rates.yaml (openai/)

# The bundled demo script: billing question -> order lookup -> satisfied close
# (caller_hangup after a clean-close reads RESOLVED through adjudicate).
SCRIPTED_DEMO_TURNS: tuple[str, ...] = (
    "Hi, I was charged twice on my bill.",
    "It is order ORD-4481, the August bill.",
    "Thanks, that is all. Bye!",
)

# Fixed virtual-clock layout (wall ms, call-relative): every turn is a 6000ms
# slot; spans sit at fixed offsets inside it. No real clock is ever read.
TURN_SLOT_MS = 6000
TURN_GAP_MS = 500
ASR_START_MS = 200
ASR_DURATION_MS = 1100
LLM_START_MS = 1500
LLM_DURATION_MS = 700
TOOL_START_MS = 2300
TTS_START_MS = 3100
TTS_DURATION_MS = 2200

_CALL_EPOCH = datetime(2026, 9, 8, 9, 0, 0, tzinfo=timezone.utc)


def _tokens_for(reply: str) -> tuple[int, int]:
    """Deterministic mock token counts from the reply text (fixed formulas,
    documented as mock telemetry in the module docstring)."""
    words = len(reply.split())
    return 600 + 6 * words, 8 + words


def run_conversation(
    *,
    call_id: str,
    scenario: str,
    caller_turns: list[str],
    agent_version: str = AGENT_VERSION,
) -> IngestCall:
    """Run the scripted caller turns through the mock loop and emit the call
    in ingest format (docs/INGEST.md). Raises ValueError with no turns."""
    if not caller_turns:
        raise ValueError("caller_turns must hold at least one turn")
    turns: list[IngestTurn] = []
    for index, text in enumerate(caller_turns):
        action = decide(scenario, text, index)
        base = index * (TURN_SLOT_MS + TURN_GAP_MS)
        input_tokens, output_tokens = _tokens_for(action.reply)
        tool_entries: list[IngestTool] = []
        if action.tool is not None:
            result = run_tool(action.tool, action.tool_args)
            tool_entries.append(IngestTool(
                name=result.name, kind=result.kind, effect=result.effect,
                args=result.args, start_ms=base + TOOL_START_MS,
                duration_ms=result.latency_ms,
            ))
        turns.append(IngestTurn(
            start_ms=base, end_ms=base + TURN_SLOT_MS,
            asr=IngestAsr(
                transcript=text, start_ms=base + ASR_START_MS,
                duration_ms=ASR_DURATION_MS,
            ),
            llm=IngestLlm(
                model=LLM_MODEL, input_tokens=input_tokens,
                output_tokens=output_tokens,
                decision_kind=action.decision_kind, decision=action.decision,
                output_text=action.reply,
                start_ms=base + LLM_START_MS, duration_ms=LLM_DURATION_MS,
                decision_candidates=[action.decision],
            ),
            tts=IngestTts(
                text=action.reply, start_ms=base + TTS_START_MS,
                duration_ms=TTS_DURATION_MS,
            ),
            tools=tool_entries,
        ))
    call_end_ms = turns[-1].end_ms
    return IngestCall(
        id=call_id, scenario=scenario,
        started=_CALL_EPOCH, ended=_CALL_EPOCH + timedelta(milliseconds=call_end_ms),
        end_reason="caller_hangup", agent_version=agent_version,
        telephony=IngestTelephony(billable_seconds=(call_end_ms + 999) // 1000),
        turns=turns,
    )
