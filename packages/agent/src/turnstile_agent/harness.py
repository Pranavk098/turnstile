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
    granularity: str = "sentence",
    record: bool = True,
) -> list[HarnessCall]:
    """Run ``n`` calls at the given modeled barge-in ``rate`` (deterministic
    per ``(n, rate, seed)``). The readback utterance cycles through
    ``READBACKS``; whether the caller interrupts is sampled per call; where
    is sampled uniform over the utterance's measured audio duration. The
    chunk schedule is measured ONCE per utterance occurrence -- at the
    stated chunk ``granularity`` (the atomic cancellation unit) -- and
    reused for that call's replay."""
    rng = np.random.default_rng(seed)
    schedules: dict[str, list] = {}
    calls: list[HarnessCall] = []
    for i in range(n):
        utterance = READBACKS[i % len(READBACKS)]
        if utterance not in schedules:
            # Phase 1 (measurement) -- once per utterance, before any barge-in
            # behavior for this call is drawn.
            schedules[utterance] = measure_utterance(engine, utterance, granularity)
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


def run_leadcap_sweep(
    engine: TtsEngine,
    *,
    n: int,
    rate: float,
    seed: int,
    lead_caps: list[float],
    granularity: str = "sentence",
    record: bool = True,
) -> dict[float, list[HarnessCall]]:
    """Sweep the streaming BUFFER-LEAD POLICY (``lead_cap_s``) -- the one
    parameter the waste magnitude scales with -- while holding the barge-in
    behavior FIXED: one sampling pass (same seed -> same per-call barge-in
    draws), replayed at every lead-cap value.

    Anti-tuning guarantee, same rule as the rate sweep: the modeled
    interruption pattern is drawn ONCE, before any lead_cap is applied, and
    the MEASURED phase-1 chunk schedule is measured ONCE per utterance and
    reused across every point -- ``lead_cap`` only affects the phase-2
    replay's ``generate_ahead`` cap, never the measured schedule, never the
    interruption draws. Returns ``{lead_cap: [HarnessCall, ...]}`` in the
    given order."""
    rng = np.random.default_rng(seed)
    samples: list[tuple[str, list, float | None]] = []
    schedules: dict[str, list] = {}
    for i in range(n):
        utterance = READBACKS[i % len(READBACKS)]
        if utterance not in schedules:
            schedules[utterance] = measure_utterance(engine, utterance, granularity)
        schedule = schedules[utterance]
        total_audio_s = sum(c.audio_seconds for c in schedule)
        barges = bool(rng.random() < rate)
        barge_at = (
            sample_barge_in_position(rng, total_audio_s) if barges else None
        )
        samples.append((utterance, schedule, barge_at))

    results: dict[float, list[HarnessCall]] = {}
    for cap in lead_caps:
        calls: list[HarnessCall] = []
        for i, (utterance, schedule, barge_at) in enumerate(samples):
            accounting = simulate_call(
                engine,
                utterance,
                barge_in_at_audio_s=barge_at,
                lead_cap_s=cap,
                schedule=schedule,
            )
            trace = None
            if record:
                trace = record_call(
                    accounting,
                    conversation_id=f"bargein-leadcap-{seed}-{cap:.1f}-{i:04d}",
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
        results[cap] = calls
    return results


def run_granularity_sweep(
    engine: TtsEngine,
    *,
    n: int,
    seed: int,
    granularities: list[str],
    rate: float,
    lead_cap_s: float = DEFAULT_LEAD_CAP_S,
    record: bool = True,
) -> dict[str, list[HarnessCall]]:
    """Sweep the TTS chunk GRANULARITY -- the atomic cancellation unit (a
    barge-in can only cancel unbilled work at a chunk boundary) -- at a
    FIXED barge-in rate and lead cap. Each granularity re-synthesizes every
    readback through the real engine at that granularity (MEASURED per-chunk
    chars/audio/wall -- never modeled), so finer granularities have their own
    measured schedules, not resampled ones.

    Anti-tuning guarantee, same rule as the other sweeps: within each
    granularity the phase-1 schedule is measured ONCE per utterance BEFORE
    any barge-in draw, and every point runs with the SAME ``seed``, so the
    modeled caller behavior (which calls barge in, and the underlying
    uniform position draws) is shared across granularities -- positions land
    at the same relative spot on each granularity's own measured timeline.
    Only the granularity (and the measured schedule it produces) varies.

    Returns ``{granularity: [HarnessCall, ...]}`` in the given order."""
    return {
        g: run_calls(
            engine, n=n, rate=rate, seed=seed, lead_cap_s=lead_cap_s,
            granularity=g, record=record,
        )
        for g in granularities
    }
