"""Turnstile's agent-side harness (packages/agent).

The measured barge-in waste number (brief:
docs/superpowers/briefs/glm-barge-in-measured-number.md): real Piper TTS
generation-ahead behavior recorded through the G1 ``TraceRecorder`` into
schema-v1.1 traces the built instrument prices and detects on, unchanged.

* :mod:`turnstile_agent.tts`       -- engines (real Piper + deterministic fake)
* :mod:`turnstile_agent.sim`       -- the streaming timeline + barge-in model
* :mod:`turnstile_agent.recording` -- G1 recording of one call
* :mod:`turnstile_agent.scenarios` -- the scripted readback scenario inputs
* :mod:`turnstile_agent.harness`   -- N-call driver + provenance string
* :mod:`turnstile_agent.recorder`  -- the G1 TraceRecorder (moved verbatim
  from the former turnstile_otel: live OTel emission + post-G1 timing model
  unchanged)
"""
from turnstile_agent.recorder import TraceRecorder, TurnRecorder
from turnstile_agent.sim import CallAccounting, SimClock, simulate_call
from turnstile_agent.tts import (
    FakeEngine,
    PiperEngine,
    SynthChunk,
    TtsEngine,
    split_sentences,
)

__all__ = [
    "CallAccounting",
    "SimClock",
    "simulate_call",
    "FakeEngine",
    "PiperEngine",
    "SynthChunk",
    "TtsEngine",
    "split_sentences",
    "TraceRecorder",
    "TurnRecorder",
]
