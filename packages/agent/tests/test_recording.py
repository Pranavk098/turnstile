"""Tests for recording a harness call through the G1 TraceRecorder
(turnstile_agent.recording): schema-validity, the G2 accounting on the
recorded spans, the measured tts/playback overlap, and end-to-end
price->detect compatibility with the built instrument."""
from __future__ import annotations

import pytest

from turnstile_agent import FakeEngine, simulate_call
from turnstile_agent.recording import record_call
from turnstile_agent.scenarios import (
    CALLER_INTERRUPTS,
    CALLER_OPENINGS,
    READBACKS,
)

from turnstile_pricing import price_trace
from turnstile_schema import load_rates
from turnstile_verdict import adjudicate
from turnstile_detectors import detect
from turnstile_experiments.baselines import compute_baselines

UTTERANCE = READBACKS[0]


def _accounting(barge_in_at=None):
    engine = FakeEngine()
    return simulate_call(engine, UTTERANCE, barge_in_at_audio_s=barge_in_at)


def test_recorded_trace_is_schema_valid_and_g2_holds():
    acct = _accounting(barge_in_at=None)
    trace = record_call(
        acct, conversation_id="c1",
        caller_opening=CALLER_OPENINGS[0], caller_interrupt=None,
    )
    agent_turn = trace.turns[1]
    assert len(agent_turn.tts) == 1
    tts = agent_turn.tts[0]
    # G2: chars_synthesized is what the engine GENERATED -- the full
    # utterance here (no barge-in), and explicitly NOT len(text)-derived by
    # the recorder: the value came from the accounting's billed count.
    assert tts.chars_synthesized == acct.generated_chars
    assert tts.audio_seconds_generated == pytest.approx(acct.generated_audio_s)
    assert tts.text == UTTERANCE  # the queued text; chars above are billed
    playback = agent_turn.playback[0]
    assert playback.chars_played == acct.played_chars
    assert playback.truncated_by is None
    # The caller turn carries the scripted opening ASR.
    assert trace.turns[0].asr[0].transcript == CALLER_OPENINGS[0]
    # The agent turn carries no llm spans: no LLM ran, so none is fabricated.
    assert agent_turn.llm == []


def test_barge_in_call_records_truncation_and_cross_turn_overlap():
    acct = _accounting(barge_in_at=2.0)
    trace = record_call(
        acct, conversation_id="c2",
        caller_opening=CALLER_OPENINGS[0],
        caller_interrupt=CALLER_INTERRUPTS[0],
    )
    agent_turn = trace.turns[1]
    assert agent_turn.barge_in is True
    tts = agent_turn.tts[0]
    playback = agent_turn.playback[0]
    # G2 under cancellation: billed chars < the queued text's length, and the
    # played chars are fewer still.
    assert tts.chars_synthesized < len(UTTERANCE.strip())
    assert playback.chars_played < tts.chars_synthesized
    assert playback.truncated_by == "barge_in"
    # The MEASURED streaming overlap: playback starts while the tts span is
    # still open, at the moment the first chunk's audio became ready.
    tts_end = tts.start_offset_ms + tts.duration_ms
    assert tts.start_offset_ms < playback.start_offset_ms < tts_end
    # The caller's interrupt turn overlaps the still-open agent turn (G1).
    assert len(trace.turns) == 3
    interrupt = trace.turns[2]
    assert interrupt.asr[0].transcript == CALLER_INTERRUPTS[0]
    assert (
        interrupt.wall_start_ms
        < agent_turn.wall_end_ms  # agent turn still open at that point
    )


def test_recorded_trace_flows_through_the_built_instrument_unchanged():
    acct = _accounting(barge_in_at=2.0)
    trace = record_call(
        acct, conversation_id="c3",
        caller_opening=CALLER_OPENINGS[0],
        caller_interrupt=CALLER_INTERRUPTS[0],
    )
    rates = load_rates("pricing/rates.yaml")
    priced = price_trace(trace, rates)
    verdict = adjudicate(priced)
    findings = detect(priced, verdict, compute_baselines([priced]))
    d7 = [f for f in findings if f.class_id == 7]
    assert len(d7) == 1
    # The finding is PURE TTS char-accounting waste (no llm spans -> no
    # llm_waste term): detector evidence matches the accounting exactly.
    ev = d7[0].evidence
    assert ev["chars_synthesized"] == acct.generated_chars
    assert ev["chars_played"] == acct.played_chars
    assert ev["wasted_chars"] == acct.waste_chars
    assert ev["llm_waste_usd"] == 0.0
    assert d7[0].waste_usd == pytest.approx(ev["tts_waste_usd"])
    # And the waste is real money against the rate card.
    assert d7[0].waste_usd > 0.0
