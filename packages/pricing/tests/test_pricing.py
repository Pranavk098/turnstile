"""Tests for the cost engine (packages/pricing).

Three layers:
  * Fixture layer -- price_trace() over the 23 golden fixtures: every fixture
    prices with no KeyError, and the decomposition invariants close
    (span_costs + telephony == conv_cost == stage_costs == turn_costs).
  * Formula layer -- one synthetic trace per PRD Sec.4.2 branch: cost_asr;
    cost_llm with cache_read>0 / cache_write>0 / reasoning>0 / the plain case;
    cost_tts (chars_synthesized, asserted on the barge-in fixture 07); cost_tel
    pro-rata across multiple turns.
  * Span-coverage layer -- span_costs keys exactly equal the priced-span set
    (asr + llm + tts); tool/playback/vad/context spans carry no rate-priced cost.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from turnstile_schema import PricedTrace, RateTable, load_rates, load_trace
from turnstile_schema.enums import DecisionKind, Direction, EndReason, SpeakerFirst
from turnstile_schema.rates import AsrRate, LlmRate, TelephonyRate, TtsRate
from turnstile_schema.spans import (
    AsrTranscribe, LlmDecide, TelephonyLeg, TtsSynthesize,
)
from turnstile_schema.trace import Conversation, Trace, Turn
from turnstile_pricing import price_trace

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

# Synthetic rates for the formula layer. Real fixtures resolve against the
# committed rates.yaml; these unit-test rates are constructed per-test to hit
# branches the golden corpus does not exercise (cache_read/write, reasoning).
RATE_ASR = 0.0043                       # per audio minute
RATE_TTS = 0.025                        # per 1k chars
RATE_TEL = 0.0085                       # per minute
RATE_IN = 1.0                           # per mtok input
RATE_OUT = 2.0                          # per mtok output
RATE_CACHE_READ = 0.1                   # per mtok cache-read
RATE_CACHE_WRITE = 0.25                 # per mtok cache-write


def _fixture_ids() -> list[str]:
    fixtures = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
    return [f["id"] for f in fixtures]


def _load(fid: str) -> Trace:
    return load_trace((GOLDEN / fid).with_suffix(".json"))


# --------------------------------------------------------------------------- #
# Synthetic-trace builders                                                     #
# --------------------------------------------------------------------------- #

def _conv(end_reason: EndReason = EndReason.caller_hangup) -> Conversation:
    return Conversation(
        conversation_id="c1", agent_version="v1", scenario_id="s1",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        end_reason=end_reason,
    )


def _asr_span(
    sid: str = "asr1", audio_seconds: float = 60.0,
    system: str = "deepgram", model: str = "nova-3",
) -> AsrTranscribe:
    return AsrTranscribe(
        span_id=sid, start_offset_ms=0, duration_ms=1000,
        gen_ai_system=system, gen_ai_request_model=model,
        audio_seconds=audio_seconds, is_streaming=False,
        transcript="t", confidence=0.9,
    )


def _llm_span(
    sid: str = "llm1", input_tokens: int = 1_000_000, output_tokens: int = 1_000_000,
    cache_read_tokens: int = 0, cache_write_tokens: int = 0,
    reasoning_tokens: int = 0, system: str = "openai", model: str = "gpt-5-mini",
) -> LlmDecide:
    return LlmDecide(
        span_id=sid, start_offset_ms=0, duration_ms=100,
        gen_ai_system=system, gen_ai_request_model=model,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        decision_kind=DecisionKind.compose, decision_chosen="x",
        decision_candidates=["x"], output_text="x", latency_ms=100,
    )


def _tts_span(
    sid: str = "tts1", chars_synthesized: int = 1000,
    system: str = "piper",
) -> TtsSynthesize:
    return TtsSynthesize(
        span_id=sid, start_offset_ms=0, duration_ms=100,
        gen_ai_system=system, chars_synthesized=chars_synthesized,
        audio_seconds_generated=1.0, text="x",
    )


def _leg(billable_seconds: int = 60, provider: str = "twilio") -> TelephonyLeg:
    return TelephonyLeg(
        span_id="leg", start_offset_ms=0, duration_ms=100,
        provider=provider, direction=Direction.inbound,
        billable_seconds=billable_seconds,
    )


def _turn(
    idx: int, wall_start_ms: int, wall_end_ms: int, *,
    asr: list[AsrTranscribe] = (), llm: list[LlmDecide] = (),
    tts: list[TtsSynthesize] = (),
) -> Turn:
    return Turn(
        turn_index=idx, speaker_first=SpeakerFirst.caller,
        wall_start_ms=wall_start_ms, wall_end_ms=wall_end_ms,
        asr=list(asr), llm=list(llm), tts=list(tts),
    )


def _trace(*turns: Turn, leg: TelephonyLeg | None = None) -> Trace:
    return Trace(conversation=_conv(), turns=list(turns), telephony=leg)


def _rates() -> RateTable:
    return RateTable(
        asr={"deepgram/nova-3": AsrRate(unit="audio_minute", rate=RATE_ASR)},
        llm={"openai/gpt-5-mini": LlmRate(
            unit="mtok", input=RATE_IN, output=RATE_OUT,
            cache_read=RATE_CACHE_READ, cache_write=RATE_CACHE_WRITE)},
        tts={"piper": TtsRate(unit="char_1k", rate=RATE_TTS)},
        telephony={"twilio/pstn_inbound": TelephonyRate(unit="minute", rate=RATE_TEL)},
    )


# --------------------------------------------------------------------------- #
# Fixture layer -- all 23 golden fixtures                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fid", _fixture_ids())
def test_prices_every_golden_fixture(fid):
    pt = price_trace(_load(fid), load_rates(RATES))
    assert isinstance(pt, PricedTrace)
    assert len(pt.turn_costs) == len(_load(fid).turns)


@pytest.mark.parametrize("fid", _fixture_ids())
def test_decomposition_invariants_hold(fid):
    pt = price_trace(_load(fid), load_rates(RATES))
    assert sum(pt.span_costs.values()) + pt.stage_costs["telephony"] == pytest.approx(pt.conv_cost)
    assert sum(pt.stage_costs.values()) == pytest.approx(pt.conv_cost)
    assert sum(pt.turn_costs) == pytest.approx(pt.conv_cost)


@pytest.mark.parametrize("fid", _fixture_ids())
def test_span_costs_cover_exactly_the_priced_spans(fid):
    trace = _load(fid)
    expected = {
        s.span_id
        for turn in trace.turns
        for s in (*turn.asr, *turn.llm, *turn.tts)
    }
    pt = price_trace(trace, load_rates(RATES))
    assert set(pt.span_costs) == expected


# --------------------------------------------------------------------------- #
# Formula layer -- one synthetic trace per PRD Sec.4.2 branch                   #
# --------------------------------------------------------------------------- #

def test_cost_asr_branch():
    pt = price_trace(_trace(_turn(0, 0, 1000, asr=[_asr_span(audio_seconds=60.0)])), _rates())
    assert pt.span_costs["asr1"] == pytest.approx(60.0 / 60.0 * RATE_ASR)
    assert pt.stage_costs["asr"] == pytest.approx(60.0 / 60.0 * RATE_ASR)


def test_cost_llm_plain_branch():
    span = _llm_span(input_tokens=1_000_000, output_tokens=1_000_000)
    pt = price_trace(_trace(_turn(0, 0, 1000, llm=[span])), _rates())
    expected = 1.0 * RATE_IN + 1.0 * RATE_OUT
    assert pt.span_costs["llm1"] == pytest.approx(expected)


def test_cost_llm_cache_read_branch():
    span = _llm_span(
        input_tokens=1_000_000, cache_read_tokens=500_000, output_tokens=0)
    pt = price_trace(_trace(_turn(0, 0, 1000, llm=[span])), _rates())
    expected = (0.5 * RATE_IN) + (0.5 * RATE_CACHE_READ)
    assert pt.span_costs["llm1"] == pytest.approx(expected)


def test_cost_llm_cache_write_branch():
    span = _llm_span(
        input_tokens=1_000_000, cache_write_tokens=200_000, output_tokens=0)
    pt = price_trace(_trace(_turn(0, 0, 1000, llm=[span])), _rates())
    expected = (1.0 * RATE_IN) + (0.2 * RATE_CACHE_WRITE)
    assert pt.span_costs["llm1"] == pytest.approx(expected)


def test_cost_llm_reasoning_branch():
    span = _llm_span(input_tokens=0, output_tokens=100_000, reasoning_tokens=50_000)
    pt = price_trace(_trace(_turn(0, 0, 1000, llm=[span])), _rates())
    expected = (0.1 + 0.05) * RATE_OUT
    assert pt.span_costs["llm1"] == pytest.approx(expected)


def test_cost_tts_branch():
    pt = price_trace(_trace(_turn(0, 0, 1000, tts=[_tts_span(chars_synthesized=1000)])), _rates())
    assert pt.span_costs["tts1"] == pytest.approx(1000 / 1000.0 * RATE_TTS)
    assert pt.stage_costs["tts"] == pytest.approx(1000 / 1000.0 * RATE_TTS)


def test_barge_in_fixture_07_prices_synthesized_not_played():
    """cost_tts uses chars_synthesized (184) -- the Detector-7 gap is real money."""
    rates = load_rates(RATES)
    pt = price_trace(_load("07_barge_in_waste"), rates)
    synth_cost = 184 / 1000.0 * rates.tts["piper"].rate
    played_cost = 61 / 1000.0 * rates.tts["piper"].rate
    assert pt.span_costs["t0"] == pytest.approx(synth_cost)
    assert pt.span_costs["t0"] != pytest.approx(played_cost)
    assert pt.stage_costs["tts"] == pytest.approx(synth_cost)


def test_cost_tel_pro_rata_across_multiple_turns():
    pt = price_trace(
        _trace(
            _turn(0, 0, 3000),
            _turn(1, 3000, 10000),
            leg=_leg(billable_seconds=60),
        ),
        _rates(),
    )
    tel_cost = 60.0 / 60.0 * RATE_TEL
    assert pt.stage_costs["telephony"] == pytest.approx(tel_cost)
    assert pt.turn_costs[0] == pytest.approx(tel_cost * (3000 / 10000))
    assert pt.turn_costs[1] == pytest.approx(tel_cost * (7000 / 10000))
    assert sum(pt.turn_costs) == pytest.approx(tel_cost)


def test_no_telephony_leg_prices_zero_telephony():
    pt = price_trace(_trace(_turn(0, 0, 1000, llm=[_llm_span(output_tokens=0, input_tokens=0)])), _rates())
    assert pt.stage_costs["telephony"] == 0.0
    assert sum(pt.turn_costs) == pytest.approx(pt.conv_cost)


def test_tool_and_playback_spans_are_not_priced():
    """vad / context / tool / playback carry no rate-priced cost (PRD Sec.4.2)."""
    trace = _load("00_baseline_clean")
    pt = price_trace(trace, load_rates(RATES))
    assert "tool1" not in pt.span_costs
    assert not any(sid.startswith("p") for sid in pt.span_costs)