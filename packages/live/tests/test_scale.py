"""Scale + D8-informativeness tests (TDD -- written FIRST, red).

- Inter-turn gaps come from the corpus's cited lognormal (Stivers et al.),
  sampled deterministically under the caller seed -- never the fixed 300ms
  floor that made D8 constant.
- Calls-dir resume: a persisted call JSON is scored, never re-run (no
  re-spend after a crash on a 4h run).
- Budget brake: calibrated upfront gate (measured unit cost) + mid-run halt
  projection.
- D8 varies with behavior (two seeds -> different D8 waste on the same
  scripted script shape is too strong with fakes; instead: varied gaps across
  one run's calls produce a non-constant D8 series).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_ingest.adapter import load
from turnstile_pricing import price_trace
from turnstile_schema import Baselines, load_rates
from turnstile_verdict import adjudicate
from turnstile_detectors import detect

from turnstile_live.bargein import (
    BARGE_SCRIPT,
    run_bargein_call,
)
from turnstile_live.caller import ImpatientCaller
from turnstile_live.fakes import FakeLlm, FakeStt, FakeTts
from turnstile_live.openloop import enforce_budget, estimate_worst_case_usd

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate_json(
    (ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
)


def _engines():
    return FakeStt(list(BARGE_SCRIPT)), FakeTts(), FakeLlm()


def _d8_waste(call_dict) -> float:
    priced = price_trace(load(call_dict, RATES), RATES)
    verdict = adjudicate(priced)
    return sum(f.waste_usd for f in detect(priced, verdict, BASELINES) if f.class_id == 8)


# --------------------------------------------------------------------------- #
# Sampled gaps: deterministic, non-negative, varied.                           #
# --------------------------------------------------------------------------- #

def test_gap_draws_are_deterministic_under_seed():
    first = ImpatientCaller(p_barge=0.5, seed=7)
    second = ImpatientCaller(p_barge=0.5, seed=7)
    assert [first.gap_ms() for _ in range(20)] == [second.gap_ms() for _ in range(20)]


def test_gap_draws_are_nonnegative_and_varied():
    caller = ImpatientCaller(p_barge=0.5, seed=7)
    gaps = [caller.gap_ms() for _ in range(100)]
    assert all(g >= 0 for g in gaps)
    assert len(set(gaps)) > 10  # a real distribution, not a floor


def test_gap_draws_follow_the_cited_lognormal_shape():
    """Median near Stivers' ~200ms (loose: [50, 800] brackets sampling noise
    at n=2000 without pinning the world)."""
    import statistics

    caller = ImpatientCaller(p_barge=0.5, seed=7)
    median = statistics.median(caller.gap_ms() for _ in range(2000))
    assert 50 <= median <= 800


def test_calls_use_sampled_gaps_between_turns(tmp_path):
    caller = ImpatientCaller(p_barge=0.0, pos_lo=0.25, pos_hi=0.75, seed=7)
    call, _notes = run_bargein_call(
        call_id="gap-001", scenario="billing_dispute",
        caller_texts=list(BARGE_SCRIPT), caller=caller,
        stt=FakeStt(list(BARGE_SCRIPT)), tts=FakeTts(), llm=FakeLlm(),
        audio_dir=tmp_path / "audio",
    )
    starts = [t.start_ms for t in call.turns]
    assert len(set(starts)) == len(starts)
    # Gap boundaries are sampled, not the old fixed 500ms grid.
    assert len({b - a for a, b in zip(starts, starts[1:])}) > 1


def test_d8_varies_across_calls_in_one_run(tmp_path):
    wastes = set()
    for i in range(6):
        caller = ImpatientCaller(p_barge=0.5, pos_lo=0.25, pos_hi=0.75, seed=100 + i)
        call, _notes = run_bargein_call(
            call_id=f"gap-{i:03d}", scenario="billing_dispute",
            caller_texts=list(BARGE_SCRIPT), caller=caller,
            stt=FakeStt(list(BARGE_SCRIPT)), tts=FakeTts(), llm=FakeLlm(),
            audio_dir=tmp_path / f"audio-{i}",
        )
        wastes.add(round(_d8_waste(call.model_dump(mode="json")), 9))
    assert len(wastes) > 1, "D8 must respond to varied gaps, not sit constant"


# --------------------------------------------------------------------------- #
# Resume: persisted calls score without engines.                               #
# --------------------------------------------------------------------------- #

def test_resumed_call_is_scored_not_rerun(tmp_path):
    from turnstile_live.__main__ import _score_persisted_or_run

    stt, tts, llm = _engines()
    caller = ImpatientCaller(p_barge=0.5, pos_lo=0.25, pos_hi=0.75, seed=7)
    calls_dir = tmp_path / "calls"
    calls_dir.mkdir()
    call, _notes = run_bargein_call(
        call_id="resume-001", scenario="billing_dispute",
        caller_texts=list(BARGE_SCRIPT), caller=caller,
        stt=stt, tts=tts, llm=llm, audio_dir=tmp_path / "audio",
    )
    (calls_dir / "resume-001.json").write_text(
        __import__("json").dumps(call.model_dump(mode="json")), encoding="utf-8")

    class ExplodingStt:
        def transcribe_wav(self, path):
            raise AssertionError("engine called on resume -- would re-spend")

    scored, fresh, res_in, res_out = _score_persisted_or_run(
        "resume-001", calls_dir, RATES, BASELINES,
        lambda: run_bargein_call(
            call_id="resume-001", scenario="billing_dispute",
            caller_texts=list(BARGE_SCRIPT),
            caller=ImpatientCaller(p_barge=0.5, pos_lo=0.25, pos_hi=0.75, seed=7),
            stt=ExplodingStt(), tts=tts, llm=llm, audio_dir=tmp_path / "audio2"),
    )
    assert fresh is False
    assert scored["tts_spend"] > 0.0
    assert res_in > 0 and res_out > 0  # usage survives the resume


# --------------------------------------------------------------------------- #
# Budget: calibrated gate + mid-run brake.                                     #
# --------------------------------------------------------------------------- #

def test_calibrated_gate_passes_n200_and_refuses_absurd():
    # Measured n=51 unit cost ~$0.0067/LLM-call incl. safety is far below the
    # pessimistic default bound; calibration keeps the honest n=200 allowed.
    estimate_worst_case_usd(200, 4, judges_per_convo=0)  # documents old bound
    from turnstile_live.openloop import _WORST_CASE_USD_PER_CALL

    calibrated = 0.002  # 1.2x the measured $0.00167 mean unit cost (n=51)
    assert 200 * 4 * calibrated < 2.0
    assert _WORST_CASE_USD_PER_CALL > calibrated  # default stays pessimistic
    with pytest.raises(RuntimeError):
        enforce_budget(200, 4, judges_per_convo=0,
                       worst_case_usd_per_call=0.01)  # $3.20 must refuse


def test_mean_ci_brackets_and_orders():
    from turnstile_live.bargein import mean_bootstrap_ci

    lo, hi = mean_bootstrap_ci([0.0] * 5 + [0.002] * 5, seed=0)
    assert lo <= 0.001 <= hi
    assert lo < hi
    assert mean_bootstrap_ci([], seed=0) == (0.0, 0.0)
