"""Tests for the lead-cap sweep harness entry
(turnstile_agent.harness.run_leadcap_sweep): one measured phase-1 schedule
and one sampling pass, replayed at every buffer policy -- the sweep can move
the policy but never the measurement."""
from __future__ import annotations

import pytest

from turnstile_agent import FakeEngine
from turnstile_agent.harness import run_leadcap_sweep


def test_one_measurement_pass_shared_across_every_lead_cap():
    # Same n, same seed, different numbers of cap points: the engine is
    # invoked EXACTLY as often -- phase 2 (the replay) never re-measures.
    e_single = FakeEngine()
    run_leadcap_sweep(e_single, n=6, rate=0.15, seed=9, lead_caps=[0.5])
    e_multi = FakeEngine()
    run_leadcap_sweep(e_multi, n=6, rate=0.15, seed=9, lead_caps=[0.5, 4.0])
    assert len(e_single.calls) == len(e_multi.calls)
    assert e_multi.calls == e_single.calls  # identical synthesis stream


def test_lead_cap_changes_the_policy_not_the_measured_schedule():
    engine = FakeEngine()
    sweep = run_leadcap_sweep(
        engine, n=6, rate=1.0, seed=9, lead_caps=[0.5, 2.0, 4.0]
    )
    lo, mid, hi = sweep[0.5], sweep[2.0], sweep[4.0]
    for a, b, c in zip(lo, mid, hi):
        # The measured phase-1 schedule is identical across points...
        assert a.accounting.total_audio_s == b.accounting.total_audio_s
        assert b.accounting.total_audio_s == c.accounting.total_audio_s
        assert a.accounting.intended_chars == c.accounting.intended_chars
        # ...and so is the drawn barge-in behavior (one sampling pass).
        assert a.accounting.barge_in_at_audio_s == b.accounting.barge_in_at_audio_s
        assert b.accounting.barge_in_at_audio_s == c.accounting.barge_in_at_audio_s
        # Only the POLICY moved: generated (billed) grows with the cap.
        assert a.accounting.generated_chars <= b.accounting.generated_chars
        assert b.accounting.generated_chars <= c.accounting.generated_chars


def test_bigger_lead_cap_never_hears_less_or_bills_less_per_call():
    engine = FakeEngine()
    sweep = run_leadcap_sweep(
        engine, n=8, rate=1.0, seed=3, lead_caps=[0.5, 4.0]
    )
    for a, b in zip(sweep[0.5], sweep[4.0]):
        assert b.accounting.generated_chars >= a.accounting.generated_chars
        # Heard audio is the SAME interruption position -- identical draws.
        assert a.accounting.played_audio_s == pytest.approx(b.accounting.played_audio_s)
