"""TTS engine abstraction for the barge-in harness.

The harness measures CHARACTER ACCOUNTING over a timeline: intended /
generated (billed) / played (heard). The only engine requirement is a
streaming ``synthesize_stream(text)`` that yields per-chunk
:class:`SynthChunk` records carrying, for each chunk actually synthesized:

* ``chars``       -- the characters in that chunk (these are the BILLED
  characters; G2 holds by construction -- the engine reports what it really
  synthesized, never ``len(full_text)``),
* ``audio_seconds`` -- the synthesized audio's real playback duration,
* ``wall_seconds``  -- the real wall-clock time synthesis took.

From these the harness derives the one genuinely novel measurement: the
**generation-to-realtime ratio** (audio_seconds / wall_seconds) -- how far
ahead of playback a streaming TTS actually generates, which is the mechanism
behind barge-in waste. It is measured per chunk, never assumed.

:class:`PiperEngine` is the real engine (piper-tts, in-process -- the CLI
entrypoint and its subprocess spawn are blocked by Windows Application
Control on this machine; the Python API is not). :class:`FakeEngine` is the
deterministic test double every unit test runs on, so the suite is green on
machines without piper or the voice model.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# The voice model path: overridable so the harness runs on any piper voice.
PIPER_MODEL_ENV = "TURNSTILE_PIPER_MODEL"
DEFAULT_PIPER_MODEL = os.path.join(os.path.expanduser("~"), "en_US-lessac-medium.onnx")


@dataclass(frozen=True)
class SynthChunk:
    """One synthesized chunk: the chars it bills, its real audio duration,
    and the real wall time synthesizing it took."""

    chars: int
    audio_seconds: float
    wall_seconds: float


class TtsEngine(Protocol):
    """What the harness needs from a TTS: stream ``text`` as synthesized
    chunks. Chunks must be yielded in order; a chunk that raises was never
    synthesized and must not be billed."""

    def synthesize_stream(self, text: str) -> Iterable[SynthChunk]: ...


def split_sentences(text: str) -> list[str]:
    """Split an utterance into sentence chunks (the natural streaming granularity
    for a readback; also the granularity D7's ``tts_chunking="sentence"`` remedy
    proposes). Deterministic, no dependencies."""
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]


class PiperEngine:
    """Real piper-tts synthesis, in-process (see module docstring for why not
    the CLI). Each SENTENCE becomes one SynthChunk: Piper is invoked once per
    sentence, its audio chunks are accumulated into that sentence's real audio
    duration, and the wall time of the whole call is measured -- so the
    generation-to-realtime ratio is a measurement, not an assumption."""

    def __init__(self, model_path: str | None = None, voice: Any = None) -> None:
        try:
            from piper import PiperVoice  # optional extra -- see pyproject
        except ImportError as exc:  # pragma: no cover - exercised only w/o extra
            raise RuntimeError(
                "piper-tts is not installed (install with: uv sync --extra piper "
                f"or uv pip install piper-tts): {exc}"
            ) from exc
        path = model_path or os.environ.get(PIPER_MODEL_ENV) or DEFAULT_PIPER_MODEL
        if not os.path.exists(path):
            raise RuntimeError(
                f"piper voice model not found at {path!r} -- set {PIPER_MODEL_ENV} "
                "to the path of a .onnx voice model"
            )
        self._voice = voice if voice is not None else PiperVoice.load(path)
        self.sample_rate: int = self._voice.config.sample_rate

    def synthesize_stream(self, text: str) -> Iterable[SynthChunk]:
        for sentence in split_sentences(text):
            start = time.perf_counter()
            samples = 0
            for chunk in self._voice.synthesize(sentence):
                samples += len(chunk.audio_int16_array)
            wall = time.perf_counter() - start
            if samples == 0:
                continue
            yield SynthChunk(
                chars=len(sentence),
                audio_seconds=samples / self.sample_rate,
                wall_seconds=wall,
            )


class FakeEngine:
    """Deterministic test engine: synthesizes each sentence into a chunk whose
    audio duration is ``chars * seconds_per_char`` and whose wall time is
    ``audio_seconds / rate`` -- i.e. generation runs ``rate``x faster than
    realtime. No audio, no piper, fully deterministic."""

    def __init__(self, seconds_per_char: float = 0.06, rate: float = 10.0) -> None:
        self.seconds_per_char = seconds_per_char
        self.rate = rate
        self.calls: list[str] = []

    def synthesize_stream(self, text: str) -> Iterable[SynthChunk]:
        for sentence in split_sentences(text):
            self.calls.append(sentence)
            audio = len(sentence) * self.seconds_per_char
            yield SynthChunk(
                chars=len(sentence),
                audio_seconds=audio,
                wall_seconds=audio / self.rate,
            )
