"""Unit tests for the streaming timeline + barge-in model
(turnstile_agent.sim) on the deterministic FakeEngine.

The FakeEngine synthesizes each sentence chunk with
audio_seconds = chars * 0.06 and wall_seconds = audio / 10 (generation runs
10x realtime) -- every expected number below is hand-computable. These tests
are the accounting's ground truth: G2 (billed = generated, never intended),
the lead cap, the mid-chunk heard fraction, and no-barge-in completeness.
"""
from __future__ import annotations

import pytest

from turnstile_agent import FakeEngine, simulate_call
from turnstile_agent.sim import measure_utterance

UTTERANCE = (
    "Let me confirm your order: one large pizza. Your total is twenty "
    "three fifty, correct?"
)


def _chunks(engine: FakeEngine, text: str):
    return list(engine.synthesize_stream(text))


def test_no_barge_in_plays_everything_and_wastes_nothing():
    engine = FakeEngine()
    acct = simulate_call(engine, UTTERANCE, barge_in_at_audio_s=None)
    total = sum(c.audio_seconds for c in _chunks(engine, UTTERANCE))
    assert acct.barge_in is False
    assert acct.truncated is False
    assert acct.generated_chars == acct.intended_chars
    assert acct.played_chars == acct.intended_chars
    assert acct.played_audio_s == pytest.approx(total)
    assert acct.waste_chars == 0
    # MEASURED generation rate == the fake engine's stated 10x realtime.
    assert acct.gen_rate_realtime_x == pytest.approx(10.0)


def test_barge_in_mid_utterance_bills_generation_ahead_but_only_heard_plays():
    engine = FakeEngine()
    schedule = measure_utterance(engine, UTTERANCE)
    total_audio = sum(c.audio_seconds for c in schedule)
    b = total_audio * 0.5  # interrupt halfway through the heard timeline

    acct = simulate_call(engine, UTTERANCE, barge_in_at_audio_s=b, schedule=schedule)

    assert acct.barge_in is True
    assert acct.truncated is True
    assert acct.played_audio_s == pytest.approx(b)
    # G2: billed = generated (>= played, < intended because generation is
    # cancelled past the cutoff).
    assert acct.generated_chars == sum(c.chars for c in acct.chunk_events)
    assert acct.played_chars < acct.generated_chars < acct.intended_chars
    assert acct.waste_chars == acct.generated_chars - acct.played_chars
    assert acct.waste_chars > 0
    # The achieved lead (measured): generated-but-unheard audio at cutoff.
    assert acct.achieved_lead_at_barge_in_s == pytest.approx(
        acct.generated_audio_s - acct.played_audio_s
    )


def test_barge_in_at_zero_hears_nothing_but_generation_lead_is_billed():
    engine = FakeEngine()
    acct = simulate_call(engine, UTTERANCE, barge_in_at_audio_s=0.0)
    assert acct.truncated is True
    assert acct.played_chars == 0
    assert acct.played_audio_s == 0.0
    # The lead buffer was generated (billed) before cancellation.
    assert acct.generated_chars > 0
    assert acct.waste_chars == acct.generated_chars


def test_barge_in_at_or_past_total_is_treated_as_no_barge_in():
    engine = FakeEngine()
    schedule = measure_utterance(engine, UTTERANCE)
    total_audio = sum(c.audio_seconds for c in schedule)
    acct = simulate_call(
        engine, UTTERANCE, barge_in_at_audio_s=total_audio + 5.0,
        schedule=schedule,
    )
    assert acct.barge_in is False
    assert acct.truncated is False
    assert acct.waste_chars == 0


def test_lead_cap_limits_generation_ahead_during_playback():
    engine = FakeEngine(rate=100.0)  # absurdly fast generation
    # Lead cap 0.5s: at any moment, generated-but-unheard audio <= 0.5s + one
    # chunk's granularity. Verify the invariant across the whole schedule.
    acct = simulate_call(
        engine, UTTERANCE, barge_in_at_audio_s=None, lead_cap_s=0.5
    )
    last_played_end = 0.0
    for event in acct.chunk_events:
        # Each chunk's frontier after generation may exceed the cap by at
        # most that chunk's own audio (atomic chunks).
        assert event.frontier_after_s - last_played_end <= 0.5 + event.audio_seconds + 1e-9
        last_played_end = min(
            last_played_end + event.audio_seconds, event.frontier_after_s
        )
    # ...and the whole utterance still plays out with zero waste.
    assert acct.waste_chars == 0


def test_schedule_is_reused_and_never_remeasured_per_call():
    engine = FakeEngine()
    schedule = measure_utterance(engine, UTTERANCE)
    calls_before = len(engine.calls)
    a = simulate_call(engine, UTTERANCE, barge_in_at_audio_s=1.0, schedule=schedule)
    b = simulate_call(engine, UTTERANCE, barge_in_at_audio_s=None, schedule=schedule)
    # The sim replays the measured schedule: NO extra engine invocations.
    assert len(engine.calls) == calls_before
    # ...and the measured schedule is identical across calls.
    assert a.total_audio_s == b.total_audio_s


def test_engine_producing_nothing_is_an_error():
    class _Dead:
        def synthesize_stream(self, text, granularity="sentence"):
            return iter(())

    with pytest.raises(ValueError):
        simulate_call(_Dead(), UTTERANCE, barge_in_at_audio_s=None)
