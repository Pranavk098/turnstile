"""Record one harness call through the G1 ``TraceRecorder``.

Every call becomes a schema-v1.1 ``Trace`` the built instrument consumes
UNCHANGED (``price_trace`` -> ``adjudicate`` -> ``detect``): the agent turn
carries the ``tts.synthesize`` span (``chars_synthesized`` = GENERATED/BILLED
per G2 -- never ``len(text)``, never the intended count) and the matching
``audio.playback`` span (``chars_played`` = HEARD, ``truncated_by="barge_in"``
when the modeled interruption cut it off).

Timing: the recorder is driven by a :class:`SimClock` the harness advances to
ABSOLUTE targets -- measured wall time for synthesis, modeled audio time for
playback. Because the clock is set to each span's exact end position before
that span is recorded, the recorder's monotone rounding can never produce a
negative duration. The playback span starts ``first_chunk_wall_s`` into the
tts span (the MEASURED moment the first synthesized audio is ready -- G1's
``into_previous_ms`` overlap, the exact expressibility the recorder redesign
landed for). No llm.decide spans are recorded: the harness runs no LLM
(brief: out of scope), and fabricating token counts would smuggle the
synthetic-corpus sin back in -- D7's finding on these traces is therefore
PURE TTS character-accounting waste, which is precisely the novel quantity.
"""
from __future__ import annotations

from turnstile_otel.recorder import TraceRecorder
from turnstile_schema.enums import EndReason, SpeakerFirst
from turnstile_schema.trace import Trace

from turnstile_agent.scenarios import SCENARIO_ID
from turnstile_agent.sim import (
    CALLER_INTERRUPT_AUDIO_S,
    CallAccounting,
    SimClock,
)

AGENT_VERSION = "bargein-harness@1"
TTS_SYSTEM = "piper"
CALLER_OPENING_AUDIO_S = 0.8  # scripted model input, stated duration


def record_call(
    accounting: CallAccounting,
    *,
    conversation_id: str,
    caller_opening: str,
    caller_interrupt: str | None,
) -> Trace:
    """Record one call (opening -> agent readback with modeled barge-in) as a
    schema-valid trace. ``caller_interrupt`` is given iff the call has a
    barge-in; it is recorded as the caller's second ASR span (a scripted
    model input -- see scenarios.py)."""
    clock = SimClock()
    rec = TraceRecorder(conversation_id, AGENT_VERSION, SCENARIO_ID, clock=clock)

    # -- Turn 0: the caller's scripted opening (modeled duration; labeled).
    caller = rec.start_turn(0, SpeakerFirst.caller)
    clock.advance(CALLER_OPENING_AUDIO_S)
    caller.record_asr(
        gen_ai_system="deepgram",
        gen_ai_request_model="nova-3",
        audio_seconds=CALLER_OPENING_AUDIO_S,
        is_streaming=False,
        transcript=caller_opening,
        confidence=1.0,
    )
    caller.close()

    # -- Turn 1: the agent's readback. Synthesis advances the clock by its
    #    MEASURED wall time; the tts span's duration IS that measurement.
    agent = rec.start_turn(1, SpeakerFirst.agent, barge_in=accounting.truncated)
    turn_start_s = clock.seconds
    clock.advance(turn_start_s + accounting.generated_wall_s)  # absolute
    agent.record_tts(
        gen_ai_system=TTS_SYSTEM,
        text=accounting.utterance,  # the queued text; chars below are G2's
        audio_seconds_generated=accounting.generated_audio_s,
        chars_synthesized=accounting.generated_chars,
    )

    # -- Playback starts when the FIRST chunk's audio is ready (measured),
    #    i.e. overlapping the tts span, and runs on the audio timeline.
    first_audio_ready_s = turn_start_s + accounting.first_chunk_wall_s
    clock.advance(first_audio_ready_s + accounting.played_audio_s)  # absolute
    agent.record_playback(
        chars_played=accounting.played_chars,
        audio_seconds_played=accounting.played_audio_s,
        truncated_by="barge_in" if accounting.truncated else None,
        at_ms=round(first_audio_ready_s * 1000),
    )

    # -- The interruption itself: the caller's scripted line lands exactly at
    #    the barge-in point on the heard-audio timeline. G1 independent
    #    lifetimes: this (caller) turn opens and records while the agent turn
    #    is still open -- the cross-turn overlap shape.
    if accounting.truncated and caller_interrupt is not None:
        clock.advance(first_audio_ready_s + (accounting.barge_in_at_audio_s or 0.0))
        interrupt_turn = rec.start_turn(2, SpeakerFirst.caller)
        clock.advance(clock.seconds + CALLER_INTERRUPT_AUDIO_S)
        interrupt_turn.record_asr(
            gen_ai_system="deepgram",
            gen_ai_request_model="nova-3",
            audio_seconds=CALLER_INTERRUPT_AUDIO_S,
            is_streaming=False,
            transcript=caller_interrupt,
            confidence=1.0,
        )
        interrupt_turn.close()

    agent.close()
    return rec.finalize(EndReason.caller_hangup)
