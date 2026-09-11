"""Real-voice loop (Phase 2): spoken caller turns in, ingest call out.

Same turn shape as the text loop, but every signal is measured: caller text
is synthesized to wav (Piper, local), transcribed by local Whisper (the
transcript STT actually heard is what the agent decides on), the reply is
decided by the capped LLM policy (or the mock policy on fallback) and
synthesized to wav (Piper, local). Token counts for LLM turns come from the
API usage block; char counts come from the engine's own accounting.

G2 honesty: `chars_synthesized`/`chars_played` are the Piper engine's
REPORTED generated counts (the harness's own billing invariant: sums exact),
and playback is complete (no barge-in in this loop), so played == generated.
Nothing here is `len(text)` as an unmeasured stand-in: the text WAS
synthesized by the engine reporting the count. Calls without engines use the
test fakes in `tests/test_voice.py` (never committed telemetry).

Engines are injected (Protocols below): unit tests run on fakes with zero
deps; the live run wires Whisper + Piper + the capped LLM. Heavy imports
(faster_whisper, piper, openai) are lazy inside the real engines so `import
turnstile_live.voice` stays light and green everywhere.
"""
from __future__ import annotations

import os
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from turnstile_ingest.model import (
    IngestAsr,
    IngestCall,
    IngestLlm,
    IngestTelephony,
    IngestTool,
    IngestTts,
    IngestTurn,
)

from turnstile_live.tools import run_tool as run_mock_tool

AGENT_VOICE_VERSION = "turnstile-live voice@v1"
LLM_MODEL_DEFAULT = "gpt-5-mini"  # must resolve in pricing/rates.yaml (openai/)
MODEL_CAP_ENV = "TURNSTILE_PAID_MODEL_CAP"
PAID_GATE_ENV = "TURNSTILE_ALLOW_PAID"

# Candidate universe the live LLM routes among on turn 0 (mirrors the
# corpus's enriched route candidates + the baselined ids in docs/INGEST.md).
ROUTE_CANDIDATES: tuple[str, ...] = (
    "order_status", "tech_support", "refund", "billing_dispute",
    "cancel_subscription", "appointment_reschedule", "other",
)

# Turn-appropriate decision labels for the open-loop runner (see
# turnstile_live.openloop): the route universe on turn 0, action labels after.
# The model may ONLY pick offered labels -- so the offered set must cover
# everything the baseline policy can emit, plus (for mutation scenarios) the
# registry-required terminal tool. Offering less forces divergence and makes
# preservation unmeasurable (observed: route-labels-only offered zero ways to
# act, scoring 0.0 by construction).
TOOL_LABELS = frozenset({"lookup_invoices"})
ESCALATE_LABELS = frozenset({"escalate"})


def kind_for_label(label: str, turn_index: int) -> str:
    """Map a chosen label to its decision kind (pure, unit-tested)."""
    if label in TOOL_LABELS:
        return "tool_select"
    if label in ESCALATE_LABELS:
        return "escalate_check"
    if turn_index == 0:
        return "route"
    return "compose"

_CALL_EPOCH = datetime(2026, 9, 10, 9, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class TtsObservation:
    """What synthesizing one utterance produced (engine-measured)."""

    chars_synthesized: int
    chars_played: int
    audio_seconds: float
    wall_seconds: float


@dataclass(frozen=True)
class LlmDecision:
    """One live LLM decision (usage + latency measured, never modeled)."""

    decision_kind: str
    decision: str
    reply: str
    input_tokens: int
    output_tokens: int
    fallback: bool = False
    latency_ms: float = 0.0


class SttEngine(Protocol):
    def transcribe_wav(self, path: Path) -> tuple[str, float]:
        """Transcribe a wav file -> (transcript, measured audio seconds)."""
        ...


class TtsEngine(Protocol):
    def synth_to_wav(self, text: str, path: Path) -> TtsObservation:
        """Synthesize text to a wav file -> engine-measured observation."""
        ...


class LlmPolicy(Protocol):
    def decide(
        self, scenario: str, transcript: str, turn_index: int,
        candidates: tuple[str, ...] | None,
    ) -> LlmDecision: ...


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def run_voice_conversation(
    *,
    call_id: str,
    scenario: str,
    caller_texts: list[str],
    stt: SttEngine,
    tts: TtsEngine,
    llm: LlmPolicy,
    audio_dir: str | Path,
    agent_version: str = AGENT_VOICE_VERSION,
) -> tuple[IngestCall, dict[str, Any]]:
    """Run scripted caller texts through real-voice engines; emit the call.

    Per turn: synthesize the caller text (same voice -- stated simplification),
    STT it, decide via the LLM policy, run a mock tool on tool_select, and
    synthesize the reply. Returns (IngestCall, report) where the report
    carries wav paths + per-turn provenance (transcripts, fallbacks,
    measured timings). Raises ValueError with no turns.
    """
    if not caller_texts:
        raise ValueError("caller_texts must hold at least one turn")
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    turns: list[IngestTurn] = []
    turn_notes: list[dict[str, Any]] = []
    caller_wavs: list[str] = []
    agent_wavs: list[str] = []
    cursor_ms = 0
    for index, scripted in enumerate(caller_texts):
        caller_wav = audio_dir / f"caller-{index}.wav"
        tts.synth_to_wav(scripted, caller_wav)
        transcript, asr_seconds = stt.transcribe_wav(caller_wav)
        asr_ms = int(round(asr_seconds * 1000))
        decision = llm.decide(scenario, transcript, index, ROUTE_CANDIDATES)
        llm_ms = int(round(decision.latency_ms))
        tool_entries: list[IngestTool] = []
        tool_ms = 0
        if decision.decision_kind == "tool_select":
            result = run_mock_tool(decision.decision, {})
            tool_ms = 300
            tool_entries.append(IngestTool(
                name=result.name, kind=result.kind, effect=result.effect,
                args=result.args, start_ms=cursor_ms + asr_ms + llm_ms,
                duration_ms=tool_ms,
            ))
        agent_wav = audio_dir / f"agent-{index}.wav"
        obs = tts.synth_to_wav(decision.reply, agent_wav)
        tts_ms = int(round(obs.audio_seconds * 1000))
        llm_start = cursor_ms + asr_ms
        tts_start = llm_start + llm_ms + tool_ms
        turn_end = tts_start + tts_ms + 300
        turns.append(IngestTurn(
            start_ms=cursor_ms, end_ms=turn_end,
            asr=IngestAsr(
                transcript=transcript, start_ms=cursor_ms, duration_ms=asr_ms,
            ),
            llm=IngestLlm(
                model=LLM_MODEL_DEFAULT,
                input_tokens=decision.input_tokens,
                output_tokens=decision.output_tokens,
                decision_kind=decision.decision_kind, decision=decision.decision,
                output_text=decision.reply,
                start_ms=llm_start, duration_ms=llm_ms,
                decision_candidates=[decision.decision],
            ),
            tts=IngestTts(
                text=decision.reply, start_ms=tts_start, duration_ms=tts_ms,
                chars_synthesized=obs.chars_synthesized,
                chars_played=obs.chars_played,
            ),
            tools=tool_entries,
        ))
        caller_wavs.append(str(caller_wav))
        agent_wavs.append(str(agent_wav))
        turn_notes.append({
            "scripted": scripted, "heard": transcript,
            "decision": decision.decision, "llm_fallback": decision.fallback,
            "asr_seconds": asr_seconds, "tts_chars": obs.chars_synthesized,
            "tts_audio_seconds": obs.audio_seconds,
        })
        cursor_ms = turn_end + 500
    call_end_ms = turns[-1].end_ms
    call = IngestCall(
        id=call_id, scenario=scenario,
        started=_CALL_EPOCH,
        ended=_CALL_EPOCH + timedelta(milliseconds=call_end_ms),
        end_reason="caller_hangup", agent_version=agent_version,
        telephony=IngestTelephony(billable_seconds=(call_end_ms + 999) // 1000),
        turns=turns,
    )
    report = {
        "agent_version": agent_version,
        "caller_wavs": caller_wavs,
        "agent_wavs": agent_wavs,
        "turns": turn_notes,
    }
    return call, report


# --------------------------------------------------------------------------- #
# Real engines (live run only; lazy heavy imports).                            #
# --------------------------------------------------------------------------- #

def _import_faster_whisper():
    """Import faster_whisper, working around blocked `av` DLLs on Windows
    Application Control machines: the array-transcribe path never touches the
    audio decoder, so a stub `av` module suffices there. Normal import first;
    the stub is a documented fallback, not the default."""
    try:
        from faster_whisper import WhisperModel

        return WhisperModel
    except ImportError as exc:
        if "av" not in str(exc).lower() and "dll" not in str(exc).lower():
            raise
    import sys
    import types

    sys.modules.setdefault("av", types.ModuleType("av"))
    from faster_whisper import WhisperModel

    return WhisperModel


def _read_mono16(path: Path, target_rate: int = 16000):
    """Read a wav file to float32 mono at target_rate (stdlib wave + numpy
    linear resample -- no FFmpeg, exact PCM decode; the resample is the only
    approximation, stated here, and immaterial for clear synthetic speech)."""
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        n_channels = wav.getnchannels()
        sampwidth = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sampwidth != 2:
        raise ValueError(f"expected 16-bit wav, got {sampwidth * 8}-bit: {path}")
    samples = np.frombuffer(frames, dtype=np.int16).reshape(-1, n_channels)
    mono = samples.mean(axis=1)  # multi-channel -> mono mixdown
    if rate != target_rate:
        positions = np.linspace(0, len(mono) - 1, int(round(len(mono) * target_rate / rate)))
        mono = np.interp(positions, np.arange(len(mono)), mono).astype(np.float32)
    return (mono / 32768.0).astype(np.float32)


class WhisperStt:
    """Local Whisper STT (faster-whisper, free, no network at transcribe
    time; the model downloads once from HF on first construction)."""

    def __init__(self, model_name: str = "tiny.en") -> None:
        WhisperModel = _import_faster_whisper()
        self._model = WhisperModel(model_name)

    def transcribe_wav(self, path: Path) -> tuple[str, float]:
        audio = _read_mono16(Path(path))
        segments, _info = self._model.transcribe(audio, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, _wav_seconds(Path(path))


class PiperTts:
    """Local Piper TTS (in-process, free): wav bytes via piper's PiperVoice,
    char/audio accounting via the harness's own PiperEngine (reuse by import
    -- the barge-in harness itself is never modified)."""

    def __init__(self, model_path: str | None = None) -> None:
        from turnstile_agent.tts import PiperEngine

        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError(
                "piper-tts is not installed (uv pip install piper-tts)"
            ) from exc
        self._accounting = PiperEngine(model_path=model_path)
        import os

        from turnstile_agent.tts import DEFAULT_PIPER_MODEL, PIPER_MODEL_ENV

        resolved = (
            model_path or os.environ.get(PIPER_MODEL_ENV) or DEFAULT_PIPER_MODEL
        )
        self._voice = PiperVoice.load(resolved)
        self._sample_rate = self._voice.config.sample_rate

    def synth_to_wav(self, text: str, path: Path) -> TtsObservation:
        import struct

        chunks = list(self._accounting.synthesize_stream(text))
        samples: list[int] = []
        for audio in self._voice.synthesize(text):
            samples.extend(int(v) for v in audio.audio_int16_array)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._sample_rate)
            wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        audio_seconds = len(samples) / self._sample_rate if samples else 0.0
        return TtsObservation(
            chars_synthesized=sum(c.chars for c in chunks),
            chars_played=sum(c.chars for c in chunks),
            audio_seconds=audio_seconds,
            wall_seconds=sum(c.wall_seconds for c in chunks),
        )


class CappedLlmPolicy:
    """Real LLM decisions inside the free small-model bucket (owner-gated:
    refuses unless TURNSTILE_ALLOW_PAID=1, mirroring OpenAIBackend). The model
    is asked for exactly one candidate label; when no candidate is contained
    the mock policy decides instead (fallback=True, reported -- never a
    fabricated label)."""

    def __init__(
        self,
        model: str | None = None,
        candidates: tuple[str, ...] = ROUTE_CANDIDATES,
    ) -> None:
        if os.environ.get(PAID_GATE_ENV) != "1":
            raise RuntimeError(
                "CappedLlmPolicy refuses to run: set TURNSTILE_ALLOW_PAID=1 "
                "to explicitly authorize real (paid) OpenAI API calls."
            )
        self._model = (
            model or os.environ.get(MODEL_CAP_ENV) or LLM_MODEL_DEFAULT
        )
        self._candidates = list(candidates)

    def decide(
        self, scenario: str, transcript: str, turn_index: int,
        candidates: tuple[str, ...] | None,
    ) -> LlmDecision:
        from openai import OpenAI

        from turnstile_live.policy import decide as mock_decide

        labels = ", ".join(self._candidates)
        start = time.perf_counter()
        client = OpenAI()
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": (
                    f"You are the voice agent for scenario '{scenario}'. "
                    "Reply naturally, but include exactly one of these "
                    f"decision labels verbatim in your reply: {labels}."
                )},
                {"role": "user", "content": transcript},
            ],
            timeout=60.0,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        low = text.lower()
        offered = list(candidates) if candidates is not None else list(self._candidates)
        hits = [c for c in offered if c.lower() in low]
        if hits:
            label = max(hits, key=len)
            return LlmDecision(
                decision_kind=kind_for_label(label, turn_index),
                decision=label, reply=text,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                fallback=False, latency_ms=latency_ms,
            )
        mock = mock_decide(scenario, transcript, turn_index)
        return LlmDecision(
            decision_kind=mock.decision_kind, decision=mock.decision,
            reply=mock.reply, input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            fallback=True, latency_ms=latency_ms,
        )


# --------------------------------------------------------------------------- #
# Function-calling policy (Phase 5): the model gets real tools.               #
# --------------------------------------------------------------------------- #

# name -> (description, {param: json-type}). Small, real params; the mock
# tools accept anything, but these schemas are what the model actually sees.
_KNOWN_FUNCTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "lookup_account": (
        "Look up a caller account by id.",
        {"account_id": "string"},
    ),
    "lookup_invoices": (
        "Look up invoices for an order.",
        {"order_id": "string"},
    ),
    "retrieve_kb_article": (
        "Retrieve a help-center article by topic.",
        {"topic": "string"},
    ),
    "process_refund": (
        "Refund a charged order back to its payment method.",
        {"order_id": "string", "amount_usd": "number"},
    ),
    "adjust_billing": (
        "Adjust an incorrect bill.",
        {"order_id": "string", "amount_usd": "number"},
    ),
    "reschedule_appointment": (
        "Move an appointment to a new time.",
        {"appointment_id": "string", "new_time": "string"},
    ),
    "cancel_subscription": (
        "Cancel a subscription.",
        {"account_id": "string"},
    ),
}

_LOOKUP_FUNCTION_NAMES: tuple[str, ...] = (
    "lookup_account", "lookup_invoices", "retrieve_kb_article",
)


def _function_schema(name: str) -> dict:
    description, params = _KNOWN_FUNCTIONS[name]
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {
            field: {"type": ftype} for field, ftype in params.items()
        }, "additionalProperties": False},
    }}


def function_schemas_for(scenario: str) -> list[dict]:
    """OpenAI function schemas for a scenario: the lookup tools plus the
    registry-required terminal tool when the scenario has one (unknown
    required names are never offered -- the model can only invoke real
    mock tools). Pure, deterministic, no network."""
    from turnstile_verdict.registry import lookup

    names = list(_LOOKUP_FUNCTION_NAMES)
    spec = lookup(scenario)
    required = spec.requires_mutation if spec is not None else None
    if required is not None and required in _KNOWN_FUNCTIONS and required not in names:
        names.append(required)
    return [_function_schema(name) for name in names]


class FunctionCallingPolicy:
    """Real tool-calling decisions inside the free small-model bucket
    (owner-gated: refuses unless TURNSTILE_ALLOW_PAID=1). The scenario's
    tools ride as OpenAI function schemas -- the model can INVOKE one
    instead of composing prose. A tool call records tool_select + the
    function name; the harness runs the existing mock tool (single-source
    `_tools_for`), which commits the registry-required tool when selected.

    Content handling: model text rides through verbatim; a tool-only turn
    (no content) records output_text "" -- the TRUE record that the model
    acted without speaking, never a fabricated utterance. A turn with
    neither tool calls nor a parseable label falls back to the mock policy
    (fallback=True, reported). `client=` injects a fake for tests."""

    def __init__(
        self,
        model: str | None = None,
        client: Any | None = None,
    ) -> None:
        if os.environ.get(PAID_GATE_ENV) != "1":
            raise RuntimeError(
                "FunctionCallingPolicy refuses to run: set TURNSTILE_ALLOW_PAID=1 "
                "to explicitly authorize real (paid) OpenAI API calls."
            )
        self._model = (
            model or os.environ.get(MODEL_CAP_ENV) or LLM_MODEL_DEFAULT
        )
        self._client = client

    def decide(
        self, scenario: str, transcript: str, turn_index: int,
        candidates: tuple[str, ...] | None,
    ) -> LlmDecision:
        from turnstile_live.policy import decide as mock_decide

        start = time.perf_counter()
        client = self._client
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": (
                    f"You are the voice agent for scenario '{scenario}'. "
                    "Use the provided tools when the caller needs action; "
                    "otherwise reply naturally in one or two sentences."
                )},
                {"role": "user", "content": transcript},
            ],
            tools=function_schemas_for(scenario),
            timeout=60.0,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        message = response.choices[0].message
        usage = response.usage
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            name = tool_calls[0].function.name
            return LlmDecision(
                decision_kind="tool_select", decision=name,
                reply=(message.content or "").strip(),
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                fallback=False, latency_ms=latency_ms,
            )
        text = (message.content or "").strip()
        from turnstile_live.openloop import candidates_for

        offered = list(candidates_for(scenario, turn_index))
        hits = [c for c in offered if c.lower() in text.lower()]
        if hits:
            label = max(hits, key=len)
            return LlmDecision(
                decision_kind=kind_for_label(label, turn_index),
                decision=label, reply=text,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                fallback=False, latency_ms=latency_ms,
            )
        mock = mock_decide(scenario, transcript, turn_index)
        return LlmDecision(
            decision_kind=mock.decision_kind, decision=mock.decision,
            reply=mock.reply, input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            fallback=True, latency_ms=latency_ms,
        )
