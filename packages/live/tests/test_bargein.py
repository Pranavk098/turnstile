"""Phase-4 tests (TDD -- written FIRST, red): the interruption-heavy caller
samples deterministically under a seed, interruption positions map to played
chars exactly, barged turns emit D7-firing ingest, and the sweep aggregation
matches the harness's D7-share definition (d7_waste / tts_spend) with a CI.
All free (fake engines); the paid run only swaps in Whisper/Piper/capped-LLM.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_detectors import detect
from turnstile_ingest import parse_call
from turnstile_ingest.adapter import load
from turnstile_pricing import price_trace
from turnstile_schema import Baselines, load_rates
from turnstile_verdict import adjudicate

from turnstile_live.bargein import (
    aggregate_sweep,
    d7_share_of_tts_spend,
    run_bargein_call,
    score_call,
)
from turnstile_live.caller import ImpatientCaller
from turnstile_live.fakes import FakeLlm, FakeStt, FakeTts

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate_json(
    (ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
)

SCRIPT = (
    "Hi, I was charged twice on my bill. This is ridiculous.",
    "No, listen — order ORD-4481, the August bill. Fix it now.",
    "Just tell me the refund amount. Now.",
    "Fine. Thanks, bye.",
)


def _engines(transcripts=None):
    return (
        FakeStt(list(transcripts or SCRIPT)),
        FakeTts(audio_seconds=4.0),
        FakeLlm(),
    )


# --------------------------------------------------------------------------- #
# Caller sampling: deterministic under seed, bounded positions.                #
# --------------------------------------------------------------------------- #

def test_same_seed_same_barge_sequence():
    first = ImpatientCaller(p_barge=0.5, pos_lo=0.25, pos_hi=0.75, seed=11)
    second = ImpatientCaller(p_barge=0.5, pos_lo=0.25, pos_hi=0.75, seed=11)
    assert [first.maybe_barge_in() for _ in range(20)] == [
        second.maybe_barge_in() for _ in range(20)]


def test_positions_stay_inside_the_window():
    caller = ImpatientCaller(p_barge=1.0, pos_lo=0.25, pos_hi=0.75, seed=3)
    positions = [caller.maybe_barge_in() for _ in range(30)]
    assert all(f is not None and 0.25 <= f <= 0.75 for f in positions)


def test_p_zero_never_barges_p_one_always_barges():
    quiet = ImpatientCaller(p_barge=0.0, pos_lo=0.25, pos_hi=0.75, seed=3)
    assert all(quiet.maybe_barge_in() is None for _ in range(10))
    rude = ImpatientCaller(p_barge=1.0, pos_lo=0.25, pos_hi=0.75, seed=3)
    assert all(rude.maybe_barge_in() is not None for _ in range(10))


def test_utterances_come_from_the_script_in_order():
    caller = ImpatientCaller(p_barge=0.5, pos_lo=0.25, pos_hi=0.75, seed=3)
    assert [caller.utterance(i, SCRIPT) for i in range(4)] == list(SCRIPT)


# --------------------------------------------------------------------------- #
# Emission: barged turns carry played < synthesized and fire D7.               #
# --------------------------------------------------------------------------- #

def test_barged_call_marks_barge_in_and_fires_d7(tmp_path):
    stt, tts, llm = _engines()
    caller = ImpatientCaller(p_barge=1.0, pos_lo=0.5, pos_hi=0.5, seed=3)
    call, _notes = run_bargein_call(
        call_id="barge-001", scenario="billing_dispute",
        caller_texts=list(SCRIPT), caller=caller,
        stt=stt, tts=tts, llm=llm, audio_dir=tmp_path / "audio",
    )
    parsed = parse_call(call.model_dump(mode="json"))
    barged = [t for t in parsed.turns if t.barge_in]
    assert barged, "p=1.0 must barge at least one agent turn"
    for turn in barged:
        assert turn.tts.chars_played < turn.tts.chars_synthesized
        assert turn.tts.chars_played == round(turn.tts.chars_synthesized * 0.5)

    priced = price_trace(load(call, RATES), RATES)
    verdict = adjudicate(priced)
    d7 = [f for f in detect(priced, verdict, BASELINES) if f.class_id == 7]
    assert d7, "interrupted audio must produce a class-7 finding"
    assert d7[0].evidence["wasted_chars"] > 0


def test_quiet_call_has_no_d7(tmp_path):
    stt, tts, llm = _engines()
    caller = ImpatientCaller(p_barge=0.0, pos_lo=0.25, pos_hi=0.75, seed=3)
    call, _notes = run_bargein_call(
        call_id="barge-002", scenario="billing_dispute",
        caller_texts=list(SCRIPT), caller=caller,
        stt=stt, tts=tts, llm=llm, audio_dir=tmp_path / "audio",
    )
    priced = price_trace(load(call, RATES), RATES)
    verdict = adjudicate(priced)
    assert [f for f in detect(priced, verdict, BASELINES) if f.class_id == 7] == []


def test_score_call_reports_waste_and_counts_per_class(tmp_path):
    stt, tts, llm = _engines()
    caller = ImpatientCaller(p_barge=1.0, pos_lo=0.5, pos_hi=0.5, seed=3)
    call, _notes = run_bargein_call(
        call_id="barge-003", scenario="billing_dispute",
        caller_texts=list(SCRIPT), caller=caller,
        stt=stt, tts=tts, llm=llm, audio_dir=tmp_path / "audio",
    )
    scored = score_call(call.model_dump(mode="json"), RATES, BASELINES)
    assert scored["d7_waste"] > 0.0 and scored["n_d7"] >= 1
    assert scored["tts_spend"] > 0.0
    assert {"verdict", "conv_cost", "d6_waste", "d8_waste",
            "n_d6", "n_d8"} <= set(scored)


# --------------------------------------------------------------------------- #
# Aggregation: D7 share mirrors the harness definition + CI.                   #
# --------------------------------------------------------------------------- #

def test_d7_share_matches_harness_definition():
    per_call = [(0.001, 0.02), (0.0, 0.02), (0.003, 0.02)]
    share, _lo, _hi = d7_share_of_tts_spend(per_call, seed=0)
    assert share == pytest.approx(0.004 / 0.06)


def test_d7_share_ci_brackets_the_point_estimate():
    per_call = [(0.001, 0.02)] * 10 + [(0.0, 0.02)] * 10
    share, lo, hi = d7_share_of_tts_spend(per_call, seed=0)
    assert lo <= share <= hi
    assert lo < hi


def test_d7_share_empty_is_zero():
    assert d7_share_of_tts_spend([], seed=0) == (0.0, 0.0, 0.0)


def test_aggregate_sweep_groups_by_level():
    table = aggregate_sweep(
        {"p0.25": [(0.001, 0.02)] * 4, "p0.50": [(0.002, 0.02)] * 4}, seed=0)
    assert set(table) == {"p0.25", "p0.50"}
    assert table["p0.50"]["d7_share"] > table["p0.25"]["d7_share"]
    for cell in table.values():
        assert {"n_calls", "n_barged", "d7_share", "d7_share_ci95",
                "d7_waste_usd", "tts_spend_usd"} <= set(cell)
