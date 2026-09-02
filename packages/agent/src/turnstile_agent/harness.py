"""The barge-in harness: N controlled calls -> measured D7 accounting.

Per call: measure the utterance's chunk schedule with the REAL engine
(phase 1), sample the modeled barge-in behavior (phase 2 -- rate from the
caller, position uniform on the heard-audio timeline), replay the timeline,
record the trace through G1, and hand the accounting back. The instrument
(``price_trace`` -> ``adjudicate`` -> ``detect``) stays in
``turnstile_experiments.bargein_report`` -- this module produces traces and
accounting only.

Provenance (the brief's non-negotiable): every artifact this harness produces
carries :data:`PROVENANCE`, which says exactly what is measured and what is
modeled. The novel, real quantity is the TTS generation-ahead waste per
barge-in; the interruption timing is a modeled, swept input. N controlled
harness calls with a scripted scenario -- not production traffic.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from turnstile_agent.recording import record_call
from turnstile_agent.scenarios import (
    CALLER_INTERRUPTS,
    CALLER_OPENINGS,
    READBACKS,
)
from turnstile_agent.sim import (
    DEFAULT_LEAD_CAP_S,
    CallAccounting,
    measure_utterance,
    sample_barge_in_position,
    simulate_call,
)
from turnstile_agent.tts import TtsEngine

PROVENANCE = (
    "Real Piper TTS generation-ahead behavior, measured on-device "
    "(per-chunk audio duration and wall-clock synthesis time); barge-in "
    "RATE modeled and swept over the cited range (turnstile_corpus."
    "distributions.BARGE_IN_RATE, telli.com 2026, default 0.15); barge-in "
    "POSITION modeled as uniform over the utterance's audio (stated null "
    "model -- no citable position distribution); N controlled harness calls "
    "with a scripted confirmation-readback scenario -- NOT production "
    "traffic, not real-time conversation, no ASR/LLM."
)


@dataclass(frozen=True)
class HarnessCall:
    """One call's inputs, accounting, and its recorded trace."""

    index: int
    rate: float
    accounting: CallAccounting
    trace: object  # turnstile_schema Trace (kept untyped here to avoid a cycle)


def run_calls(
    engine: TtsEngine,
    *,
    n: int,
    rate: float,
    seed: int,
    lead_cap_s: float = DEFAULT_LEAD_CAP_S,
    record: bool = True,
) -> list[HarnessCall]:
    """Run ``n`` calls at the given modeled barge-in ``rate`` (deterministic
    per ``(n, rate, seed)``). The readback utterance cycles through
    ``READBACKS``; whether the caller interrupts is sampled per call; where
    is sampled uniform over the utterance's measured audio duration. The
    chunk schedule is measured ONCE per utterance occurrence and reused for
    that call's replay."""
    rng = np.random.default_rng(seed)
    schedules: dict[str, list] = {}
    calls: list[HarnessCall] = []
    for i in range(n):
        utterance = READBACKS[i % len(READBACKS)]
        if utterance not in schedules:
            # Phase 1 (measurement) -- once per utterance, before any barge-in
            # behavior for this call is drawn.
            schedules[utterance] = measure_utterance(engine, utterance)
        schedule = schedules[utterance]
        total_audio_s = sum(c.audio_seconds for c in schedule)

        # Phase 2 (modeled behavior, drawn AFTER the measurement it can never
        # influence): does the caller interrupt, and where on the timeline?
        barges = bool(rng.random() < rate)
        barge_at = (
            sample_barge_in_position(rng, total_audio_s) if barges else None
        )

        accounting = simulate_call(
            engine,
            utterance,
            barge_in_at_audio_s=barge_at,
            lead_cap_s=lead_cap_s,
            schedule=schedule,
        )
        trace = None
        if record:
            trace = record_call(
                accounting,
                conversation_id=f"bargein-{seed}-{rate:.2f}-{i:04d}",
                caller_opening=CALLER_OPENINGS[i % len(CALLER_OPENINGS)],
                caller_interrupt=(
                    CALLER_INTERRUPTS[i % len(CALLER_INTERRUPTS)]
                    if accounting.truncated
                    else None
                ),
            )
        calls.append(
            HarnessCall(index=i, rate=rate, accounting=accounting, trace=trace)
        )
    return calls
