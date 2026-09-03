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
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:.!?])\s+")
_WORD_SPLIT = re.compile(r"\s+")

# Chunk-granularity policies for streaming synthesis: how finely an utterance
# is split into synthesis chunks -- which sets the ATOMIC CANCELLATION UNIT
# (a barge-in can only cancel unbilled work at a chunk boundary). "sentence"
# is today's streaming default (D6/D7's proposed remedy). "clause" splits
# additionally on comma/semicolon boundaries; "word" on every whitespace
# boundary. Each granularity re-synthesizes through the real engine (MEASURED
# chars + audio + wall time per finer chunk -- never modeled), so the sweep
# over this knob is a measured remedy comparison, not an assumption.
GRANULARITIES: tuple[str, ...] = ("sentence", "clause", "word")

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
    chunks at the stated ``granularity`` (the atomic cancellation unit).
    Chunks must be yielded in order; a chunk that raises was never
    synthesized and must not be billed."""

    def synthesize_stream(
        self, text: str, granularity: str = "sentence"
    ) -> Iterable[SynthChunk]: ...


def split_chunks(text: str, granularity: str = "sentence") -> list[str]:
    """Split an utterance into synthesis chunks at the stated granularity --
    the atomic cancellation unit for barge-in. ``sentence`` (the streaming
    default, D6/D7's proposed remedy) splits on sentence boundaries;
    ``clause`` additionally on comma/semicolon boundaries; ``word`` on every
    whitespace boundary (inter-chunk whitespace is not a billed unit at any
    granularity). Deterministic, no dependencies; every non-whitespace
    character survives exactly once at every granularity."""
    text = text.strip()
    if granularity == "sentence":
        return [s for s in _SENTENCE_SPLIT.split(text) if s]
    if granularity == "clause":
        return [s for s in _CLAUSE_SPLIT.split(text) if s]
    if granularity == "word":
        return [s for s in _WORD_SPLIT.split(text) if s]
    raise ValueError(
        f"unknown chunk granularity {granularity!r} "
        f"(known: {', '.join(GRANULARITIES)})"
    )


def split_sentences(text: str) -> list[str]:
    """Split an utterance into sentence chunks -- ``split_chunks`` at the
    default granularity (kept as a named function: it is the streaming
    default and D7's proposed remedy). Deterministic, no dependencies."""
    return split_chunks(text, "sentence")


class PiperEngine:
    """Real piper-tts synthesis, in-process (see module docstring for why not
    the CLI). Streaming granularity is Piper's OWN audio chunks (sub-second)
    within the chunk text set by the granularity knob: each synthesis chunk
    (sentence by default; clause/word via ``granularity``) is synthesized in
    one call -- its total wall time and char count are MEASURED exactly -- and the sentence's characters and wall time
    are attributed across its audio chunks proportionally to each chunk's
    audio duration (a stated attribution: a hosted streaming TTS bills per
    rendered character; locally the char<->audio map within a synthesized
    sentence is approximated proportionally, with sums exact by remainder
    correction). This keeps the billing invariant (G2: chars sum to the
    synthesized sentence) at the granularity the buffer-lead policy actually
    acts on."""

    def __init__(self, model_path: str | None = None, voice: Any = None) -> None:
        try:
            from piper import PiperVoice  # optional extra -- see pyproject
        except ImportError as exc:  # pragma: no cover - exercised only w/o extra
            raise RuntimeError(
                "piper-tts is not installed (install with: uv sync --group piper "
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

    def synthesize_stream(
        self, text: str, granularity: str = "sentence"
    ) -> Iterable[SynthChunk]:
        """Stream ``text`` as synthesized chunks at the stated granularity.
        Each chunk is synthesized in ONE voice call -- its total wall time
        and char count are MEASURED exactly -- and attributed across the
        chunk's audio chunks proportionally to each chunk's audio duration
        (a stated attribution: a hosted streaming TTS bills per rendered
        character; locally the char<->audio map within a synthesized chunk is
        approximated proportionally, with sums exact by remainder
        correction). Finer granularity = more, smaller voice calls = a
        smaller atomic cancellation unit; the per-granularity audio/wall
        differences are MEASURED and reported as-is, never modeled."""
        for chunk_text in split_chunks(text, granularity):
            start = time.perf_counter()
            audio_chunks = list(self._voice.synthesize(chunk_text))
            wall = time.perf_counter() - start
            samples = [len(c.audio_int16_array) for c in audio_chunks]
            total_samples = sum(samples)
            if total_samples == 0:
                continue
            total_audio = total_samples / self.sample_rate
            chunk_chars = len(chunk_text)
            allocated_chars = 0
            allocated_wall = 0.0
            for j, n in enumerate(samples):
                last = j == len(samples) - 1
                audio_s = n / self.sample_rate
                if last:
                    chars = chunk_chars - allocated_chars
                    chunk_wall = max(0.0, wall - allocated_wall)
                else:
                    chars = round(chunk_chars * audio_s / total_audio)
                    chunk_wall = wall * audio_s / total_audio
                allocated_chars += chars
                allocated_wall += chunk_wall
                if chars == 0 or audio_s == 0:
                    continue
                yield SynthChunk(
                    chars=chars,
                    audio_seconds=audio_s,
                    wall_seconds=chunk_wall,
                )


class FakeEngine:
    """Deterministic test engine: splits each sentence into sub-second
    streaming pieces (``max_chars_per_chunk`` characters each, mirroring a
    real streaming TTS's chunk granularity) whose audio duration is
    ``chars * seconds_per_char`` and whose wall time is
    ``audio_seconds / rate`` -- i.e. generation runs ``rate``x faster than
    realtime. No audio, no piper, fully deterministic; char sums per
    sentence are exact."""

    def __init__(
        self,
        seconds_per_char: float = 0.06,
        rate: float = 10.0,
        max_chars_per_chunk: int = 15,
    ) -> None:
        self.seconds_per_char = seconds_per_char
        self.rate = rate
        self.max_chars_per_chunk = max_chars_per_chunk
        self.calls: list[str] = []

    def synthesize_stream(
        self, text: str, granularity: str = "sentence"
    ) -> Iterable[SynthChunk]:
        for chunk_text in split_chunks(text, granularity):
            self.calls.append(chunk_text)
            for piece in _chunk_chars(chunk_text, self.max_chars_per_chunk):
                audio = len(piece) * self.seconds_per_char
                yield SynthChunk(
                    chars=len(piece),
                    audio_seconds=audio,
                    wall_seconds=audio / self.rate,
                )


def _chunk_chars(sentence: str, max_chars: int) -> list[str]:
    """Split a sentence into deterministic character-count pieces (the fake
    engine's streaming granularity). Keeps every character exactly once."""
    return [sentence[i: i + max_chars] for i in range(0, len(sentence), max_chars)]
