"""Cost engine -- turn a schema-v1.1 Trace into a PricedTrace (PRD Sec.4.2).

Single entry point ``price_trace(trace, rates) -> PricedTrace`` (PRD Sec.5,
schema v1.1). Prices every rate-priced span (asr / llm / tts) against
``pricing/rates.yaml`` and attributes the telephony leg's cost to turns
pro-rata by each turn's wall duration.

What gets priced (the four stage columns of PricedTrace are
asr / llm / tts / telephony):
  * ``AsrTranscribe``  -> cost_asr   (audio_seconds / 60 x rate_per_minute)
  * ``LlmDecide``      -> cost_llm   (token formula, see below)
  * ``TtsSynthesize``  -> cost_tts   (chars_synthesized / 1000 x rate_per_1k)
  * ``TelephonyLeg``   -> cost_tel   (billable_seconds / 60 x rate_per_minute),
                                    attributed to turns pro-rata by wall time.

vad / context / tool / playback spans carry no rate-priced cost. ``ToolCall``'s
``cost_usd`` is vendor-reported metadata, not a stage cost, and is deliberately
excluded so the stage-cost decomposition closes.

Rate-key resolution (convention documented at the top of pricing/rates.yaml):
  asr / llm span -> f"{gen_ai.system}/{gen_ai.request.model}" (bare model name)
  tts span       -> gen_ai.system alone (TtsSynthesize has no model field)
  telephony.leg  -> f"{provider}/pstn_{direction}"

Every fixture span is guaranteed to resolve (a schema-package guard test
enforces it), so a KeyError here means the resolution logic is wrong, not the
rate table.
"""
from __future__ import annotations

import math

from turnstile_schema import PricedTrace, RateTable, Trace
from turnstile_schema.spans import AsrTranscribe, LlmDecide, TelephonyLeg, TtsSynthesize

# --------------------------------------------------------------------------- #
# Rate-key resolution                                                          #
# --------------------------------------------------------------------------- #

def _asr_key(span: AsrTranscribe) -> str:
    return f"{span.gen_ai_system}/{span.gen_ai_request_model}"


def _llm_key(span: LlmDecide) -> str:
    return f"{span.gen_ai_system}/{span.gen_ai_request_model}"


def _tts_key(span: TtsSynthesize) -> str:
    return span.gen_ai_system


def _telephony_key(leg: TelephonyLeg) -> str:
    return f"{leg.provider}/pstn_{leg.direction.value}"


# --------------------------------------------------------------------------- #
# Per-stage formulas (PRD Sec.4.2 -- verbatim, do not alter)                   #
# --------------------------------------------------------------------------- #

def _cost_asr(span: AsrTranscribe, rate) -> float:
    return span.audio_seconds / 60.0 * rate.rate


def _cost_llm(span: LlmDecide, rate) -> float:
    return (
        (span.input_tokens - span.cache_read_tokens) / 1e6 * rate.input
        + span.cache_read_tokens / 1e6 * rate.cache_read
        + span.cache_write_tokens / 1e6 * rate.cache_write
        + (span.output_tokens + span.reasoning_tokens) / 1e6 * rate.output
    )


def _cost_tts(span: TtsSynthesize, rate) -> float:
    # SYNTHESIZED, never played -- the gap is Detector 7 and it is real money.
    return span.chars_synthesized / 1000.0 * rate.rate


def _cost_telephony(leg: TelephonyLeg, rate) -> float:
    return leg.billable_seconds / 60.0 * rate.rate


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def price_trace(trace: Trace, rates: RateTable) -> PricedTrace:
    """Price every span of ``trace`` against ``rates`` (PRD Sec.4.2/4.3)."""
    span_costs: dict[str, float] = {}
    stage_costs = {"asr": 0.0, "llm": 0.0, "tts": 0.0, "telephony": 0.0}
    turn_costs = [0.0] * len(trace.turns)

    for i, turn in enumerate(trace.turns):
        for span in turn.asr:
            cost = _cost_asr(span, rates.asr[_asr_key(span)])
            span_costs[span.span_id] = cost
            stage_costs["asr"] += cost
            turn_costs[i] += cost
        for span in turn.llm:
            cost = _cost_llm(span, rates.llm[_llm_key(span)])
            span_costs[span.span_id] = cost
            stage_costs["llm"] += cost
            turn_costs[i] += cost
        for span in turn.tts:
            cost = _cost_tts(span, rates.tts[_tts_key(span)])
            span_costs[span.span_id] = cost
            stage_costs["tts"] += cost
            turn_costs[i] += cost

    # Telephony cost outside turn_costs would break sum(stage_costs) ==
    # conv_cost (CR-05/10) whenever it can't be attributed pro-rata: a trace
    # where every turn has zero wall duration, or a trace with zero turns.
    # unattributed_telephony carries the leftover into conv_cost directly for
    # the zero-turn case, where there is no turn_costs slot to put it in.
    unattributed_telephony = 0.0
    if trace.telephony is not None:
        leg = trace.telephony
        tel_cost = _cost_telephony(leg, rates.telephony[_telephony_key(leg)])
        stage_costs["telephony"] = tel_cost
        if trace.turns:
            total_wall_ms = sum(t.wall_end_ms - t.wall_start_ms for t in trace.turns)
            if total_wall_ms > 0:
                for i, turn in enumerate(trace.turns):
                    wall_ms = turn.wall_end_ms - turn.wall_start_ms
                    turn_costs[i] += tel_cost * (wall_ms / total_wall_ms)
            else:
                # Every turn has zero wall duration -- pro-rata is undefined,
                # so split the telephony cost evenly across the turns.
                share = tel_cost / len(trace.turns)
                for i in range(len(trace.turns)):
                    turn_costs[i] += share
        else:
            unattributed_telephony = tel_cost

    conv_cost = sum(turn_costs) + unattributed_telephony

    priced = PricedTrace(
        trace=trace,
        span_costs=span_costs,
        turn_costs=turn_costs,
        conv_cost=conv_cost,
        stage_costs=stage_costs,
    )
    assert math.isclose(sum(stage_costs.values()), conv_cost, rel_tol=1e-9, abs_tol=1e-12)
    return priced