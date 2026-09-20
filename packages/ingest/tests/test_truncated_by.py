"""Day-4 Part C: playback ``truncated_by`` derivation (adapter contract).

The playback span's ``turnstile.truncated_by`` is ``"barge_in"`` exactly
when the turn is flagged ``barge_in`` AND both G2 char counts are present
AND ``chars_played < chars_synthesized``; otherwise ``None``. A barged
turn whose playback ran to completion (played == synthesized) had nothing
cut, so it reads ``None`` (talked-over, not yielded).
"""
from __future__ import annotations

from pathlib import Path

from turnstile_schema import load_rates
from turnstile_ingest import load

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")


def _call(*, barge_in: bool, synth: int, played: int):
    return {
        "id": "trunc-001",
        "scenario": "billing_dispute",
        "started": "2026-09-04T09:00:00Z",
        "ended": "2026-09-04T09:01:00Z",
        "end_reason": "caller_hangup",
        "telephony": {"provider": "twilio", "direction": "inbound", "billable_seconds": 60},
        "turns": [
            {
                "start_ms": 0, "end_ms": 9000, "barge_in": barge_in,
                "llm": {"model": "gpt-5-mini", "input_tokens": 900, "output_tokens": 40,
                        "decision_kind": "compose", "decision": "long_explanation",
                        "output_text": "Here is the full refund policy in detail.",
                        "start_ms": 0, "duration_ms": 700},
                "tts": {"text": "Here is the full refund policy in detail.",
                        "start_ms": 1400, "duration_ms": 5600,
                        "chars_synthesized": synth, "chars_played": played},
            }
        ],
    }


def test_barged_cut_turn_marks_truncated_by_barge_in():
    trace = load(_call(barge_in=True, synth=200, played=60), rates=RATES)
    (playback,) = trace.turns[0].playback
    assert playback.truncated_by == "barge_in"


def test_non_barged_turn_leaves_truncated_by_none():
    trace = load(_call(barge_in=False, synth=200, played=60), rates=RATES)
    (playback,) = trace.turns[0].playback
    assert playback.truncated_by is None


def test_barged_completed_playback_leaves_truncated_by_none():
    # played == synthesized: nothing was cut, so the barge did not truncate
    # playback (talked-over, not yielded).
    trace = load(_call(barge_in=True, synth=200, played=200), rates=RATES)
    (playback,) = trace.turns[0].playback
    assert playback.truncated_by is None
