"""Detector 7 -- Barge-in waste (PRD §6, row 7).

Detection rule (verbatim): `chars_synthesized > chars_played` for a turn's
tts/playback pair -- the caller interrupted (or the agent stopped) before all
synthesized speech played out. `cost_tts` bills `chars_synthesized`, never
`chars_played` (packages/pricing, PRD §4.2), so the gap is already-billed,
real money -- "Detector 7 is the demo moment" (PRD §6).

Waste calculation (verbatim): `(chars_synth - chars_played)/1000 x rate_tts`
+ attributable LLM output tokens. The tts portion is derived proportionally
from the tts span's own `PricedTrace.span_costs` entry (per the package brief:
prefer span_costs over re-deriving raw-rate math where the proportion is
equivalent). The attributable LLM cost assumes output tokens spread evenly
across the composed text by character count, so the wasted-character fraction
of the tts text maps to the same fraction of that turn's `llm.decide`
output-token cost; it uses the raw per-token output rate since it needs only
the output component of `cost_llm`, not the turn's full mixed span cost.
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict

from turnstile_detectors._rates import get_rates, llm_key

BARGE_IN_CONFIDENCE = 0.95  # exact structural match, not statistical


def detect_barge_in_waste(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    rates = get_rates()
    findings: list[Finding] = []
    for turn in trace.trace.turns:
        # Index-matched pairing (CR-01): a tts span pairs with the playback of
        # the same utterance by position, not with every playback in the
        # turn -- a naive nested loop cross-multiplies findings when a turn
        # has multiple tts/playback spans.
        for tts, playback in zip(turn.tts, turn.playback):
            wasted_chars = tts.chars_synthesized - playback.chars_played
            if wasted_chars <= 0:
                # Also covers chars_synthesized == 0 (CR-03): wasted_chars is
                # then 0 - played <= 0, so we continue before ever dividing by
                # chars_synthesized below.
                continue
            wasted_fraction = wasted_chars / tts.chars_synthesized
            tts_cost = trace.span_costs.get(tts.span_id, 0.0)
            tts_waste = tts_cost * wasted_fraction

            llm_waste = 0.0
            for llm_span in turn.llm:
                rate = rates.llm[llm_key(llm_span)]
                attributable_tokens = llm_span.output_tokens * wasted_fraction
                llm_waste += attributable_tokens / 1e6 * rate.output

            findings.append(
                Finding(
                    class_id=7,
                    turn_index=turn.turn_index,
                    span_id=tts.span_id,
                    waste_usd=tts_waste + llm_waste,
                    confidence=BARGE_IN_CONFIDENCE,
                    proposed_variant=VariantSpec(tts_chunking="sentence"),
                    evidence={
                        "chars_synthesized": tts.chars_synthesized,
                        "chars_played": playback.chars_played,
                        "wasted_chars": wasted_chars,
                        "tts_waste_usd": tts_waste,
                        "llm_waste_usd": llm_waste,
                    },
                )
            )
    return findings
