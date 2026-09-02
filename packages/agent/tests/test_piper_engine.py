"""Real-Piper integration test -- SKIPPED unless the piper extra is installed
(``uv sync --group piper``) AND a voice model is available (env
TURNSTILE_PIPER_MODEL or ~/en_US-lessac-medium.onnx). Everything the suite
depends on is covered by the fake-engine tests; this test verifies the REAL
engine's measurement contract: real audio durations, real wall times, and a
generation rate faster than realtime (the measured fact the harness exists to
capture)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from turnstile_agent.sim import measure_utterance
from turnstile_agent.tts import DEFAULT_PIPER_MODEL, PIPER_MODEL_ENV

try:
    import piper  # noqa: F401

    _PIPER_IMPORTABLE = True
except ImportError:
    _PIPER_IMPORTABLE = False

_MODEL = os.environ.get(PIPER_MODEL_ENV) or DEFAULT_PIPER_MODEL

pytestmark = pytest.mark.skipif(
    not (_PIPER_IMPORTABLE and Path(_MODEL).exists()),
    reason=f"piper not importable ({_PIPER_IMPORTABLE}) or voice model missing "
    f"at {_MODEL} -- install with `uv sync --group piper`",
)


def test_piper_engine_measures_real_generation_ahead_behavior():
    from turnstile_agent.tts import PiperEngine

    engine = PiperEngine(_MODEL)
    utterance = (
        "Let me confirm your order: one large pepperoni pizza, a side of "
        "garlic knots, and two medium soft drinks. Your total comes to "
        "twenty three dollars and fifty cents. Is that all correct?"
    )
    schedule = measure_utterance(engine, utterance)
    assert len(schedule) >= 2  # sentence-chunked
    total_audio = sum(c.audio_seconds for c in schedule)
    total_wall = sum(c.wall_seconds for c in schedule)
    assert total_audio > 3.0  # a real readback of this length is seconds long
    assert total_wall > 0.0
    # THE measured fact: local Piper generates much faster than realtime --
    # this ratio is what makes streaming TTS bill audio the caller never hears.
    assert total_audio / total_wall > 1.0
    # G2 at the engine boundary: billed chars == the text as actually chunked
    # (sentence chunks; inter-sentence whitespace is not a billed unit).
    from turnstile_agent.tts import split_sentences

    assert sum(c.chars for c in schedule) == sum(
        len(s) for s in split_sentences(utterance.strip())
    )
