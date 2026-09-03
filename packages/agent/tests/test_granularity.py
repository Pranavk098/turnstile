"""Tests for the TTS chunk-granularity knob (batch 2 T1) -- the atomic
cancellation unit of the barge-in harness. Mechanics are verified on the
deterministic FakeEngine; a separate Piper-gated test measures the real
engine when the extra + voice model are present."""
from __future__ import annotations

import pytest

from turnstile_agent.sim import simulate_call
from turnstile_agent.tts import GRANULARITIES, FakeEngine, split_chunks, split_sentences

READBACK = (
    "Let me confirm your order: one large pepperoni pizza, a side of garlic "
    "knots, and two medium soft drinks. Your total comes to twenty three "
    "dollars and fifty cents. Is that all correct?"
)


# --------------------------------------------------------------------------- #
# split_chunks: deterministic, every non-whitespace char kept exactly once.    #
# --------------------------------------------------------------------------- #

def test_sentence_granularity_matches_split_sentences():
    assert split_chunks(READBACK, "sentence") == split_sentences(READBACK)
    assert len(split_chunks(READBACK, "sentence")) == 3


def test_clause_granularity_is_finer_than_sentence():
    chunks = split_chunks(READBACK, "clause")
    assert len(chunks) > len(split_chunks(READBACK, "sentence"))
    # Clause boundaries land on , ; : and the sentence punctuation.
    assert any(c.endswith(",") for c in chunks)


def test_word_granularity_is_finer_than_clause():
    assert len(split_chunks(READBACK, "word")) > len(split_chunks(READBACK, "clause"))
    assert all(" " not in c for c in split_chunks(READBACK, "word"))


@pytest.mark.parametrize("granularity", GRANULARITIES)
def test_every_granularity_preserves_every_non_whitespace_character(granularity):
    # Only the split boundaries' whitespace is dropped; every non-whitespace
    # character survives exactly once at every granularity.
    joined = "".join(split_chunks(READBACK, granularity))
    assert [c for c in joined if not c.isspace()] == \
           [c for c in READBACK if not c.isspace()]


def test_unknown_granularity_fails_loudly():
    with pytest.raises(ValueError, match="granularity"):
        split_chunks(READBACK, "phoneme")


# --------------------------------------------------------------------------- #
# Harness mechanics on the FakeEngine: the knob flows through measurement and  #
# the G2 invariant holds at every granularity.                                 #
# --------------------------------------------------------------------------- #

def test_fake_engine_honors_the_granularity():
    engine = FakeEngine()
    list(engine.synthesize_stream(READBACK, "word"))
    # The fake records every synthesis chunk it was asked to speak: word-level
    # synthesis asks for many small chunks, sentence-level for few.
    assert len(engine.calls) == len(split_chunks(READBACK, "word"))


def test_finer_granularity_never_hears_less_or_bills_beyond_intended():
    # G2 (intended >= generated >= played) holds at every granularity, and
    # the intended chars are the same stream at every granularity (the
    # utterance minus inter-chunk whitespace).
    for g in GRANULARITIES:
        engine = FakeEngine()
        schedule = list(engine.synthesize_stream(READBACK, g))
        accounting = simulate_call(
            engine, READBACK, barge_in_at_audio_s=1.0, schedule=schedule)
        assert accounting.intended_chars >= accounting.generated_chars, g
        assert accounting.generated_chars >= accounting.played_chars, g
        assert accounting.intended_chars == sum(c.chars for c in schedule), g


def test_finer_granularity_cuts_the_unheard_waste_at_a_fixed_barge_in():
    # The measured remedy mechanism: the barge-in can only cancel unbilled
    # work at a chunk boundary, so the atomic unit -- one in-flight chunk --
    # shrinks as the granularity gets finer. The effect is cleanest where
    # the atom dominates the policy, i.e. at a lead cap SMALLER than a
    # sentence's audio: the sentence atom forces a whole extra chunk ahead,
    # word atoms barely overshoot the cap at all.
    wastes = {}
    for g in GRANULARITIES:
        engine = FakeEngine()
        schedule = list(engine.synthesize_stream(READBACK, g))
        wastes[g] = simulate_call(
            engine, READBACK, barge_in_at_audio_s=1.0,
            lead_cap_s=0.3, schedule=schedule).waste_chars
    assert wastes["word"] <= wastes["clause"] <= wastes["sentence"]
    assert wastes["word"] < wastes["sentence"]  # the floor genuinely drops


# --------------------------------------------------------------------------- #
# Granularity sweep plumbing: shared caller behavior across granularities.     #
# --------------------------------------------------------------------------- #

def test_granularity_sweep_shares_the_barge_in_pattern_across_points():
    from turnstile_agent.harness import run_granularity_sweep

    sweep = run_granularity_sweep(
        FakeEngine(), n=24, seed=11, granularities=list(GRANULARITIES),
        rate=0.5, record=False,
    )
    assert set(sweep) == set(GRANULARITIES)
    # Anti-tuning: the modeled caller behavior is IDENTICAL at every point
    # (same seed -> same barge/no-barge pattern); only the measured schedules
    # differ.
    patterns = [
        tuple(c.accounting.barge_in for c in calls)
        for calls in sweep.values()
    ]
    assert len(set(patterns)) == 1
    assert any(patterns[0])  # the shared pattern actually bites
    # Each point's accounting is deterministic per (granularity, seed).
    again = run_granularity_sweep(
        FakeEngine(), n=24, seed=11, granularities=list(GRANULARITIES),
        rate=0.5, record=False,
    )
    for g in GRANULARITIES:
        assert [c.accounting.waste_chars for c in again[g]] == \
               [c.accounting.waste_chars for c in sweep[g]]
