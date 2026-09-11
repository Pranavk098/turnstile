"""Test/dry-run doubles for the live loops (no Piper/Whisper/network).

FakeStt replays canned transcripts (duration honestly measured from the wav
header); FakeTts writes silent wavs of fixed length (its char counts are
FAKE accounting, test-only -- the live path uses engine-measured counts);
FakeLlm replays canned decisions (default: the 4-turn billing script shape).
Deterministic throughout.
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path

from turnstile_live.voice import LlmDecision, TtsObservation


class FakeStt:
    def __init__(self, transcripts: list[str]) -> None:
        self._transcripts = list(transcripts)
        self.calls = 0

    def transcribe_wav(self, path: Path) -> tuple[str, float]:
        with wave.open(str(path), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
        text = self._transcripts[min(self.calls, len(self._transcripts) - 1)]
        self.calls += 1
        return text, seconds


class FakeTts:
    def __init__(self, audio_seconds: float = 4.0, sample_rate: int = 22050) -> None:
        self.audio_seconds = audio_seconds
        self.sample_rate = sample_rate

    def synth_to_wav(self, text: str, path: Path) -> TtsObservation:
        n = int(self.audio_seconds * self.sample_rate)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(struct.pack(f"<{n}h", *([0] * n)))
        return TtsObservation(
            chars_synthesized=len(text), chars_played=len(text),
            audio_seconds=self.audio_seconds, wall_seconds=0.05,
        )


_DEFAULT_BILLING_DECISIONS = (
    ("route", "billing_dispute", "Let me look into that bill for you.", 700, 20),
    ("tool_select", "lookup_invoices", "Pulling up the invoice now.", 800, 15),
    ("compose", "inform", "Understood — checking the details.", 800, 15),
    ("compose", "close_call", "Glad I could help — anything else today?", 850, 18),
)


class FakeLlm:
    def __init__(self, decisions=None) -> None:
        self._decisions = list(decisions) if decisions is not None else list(
            _DEFAULT_BILLING_DECISIONS)
        self.calls = 0

    def decide(self, scenario, transcript, turn_index, candidates=None):
        kind, label, reply, in_tok, out_tok = self._decisions[
            min(turn_index, len(self._decisions) - 1)]
        self.calls += 1
        return LlmDecision(kind, label, reply, in_tok, out_tok, False, 0.0)
