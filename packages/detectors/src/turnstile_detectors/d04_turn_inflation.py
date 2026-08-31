"""Detector 4 -- Turn inflation (PRD §6, row 4).

Detection rule (verbatim): `turns_to_resolution > p75(intent baseline)`.
`turns_to_resolution` is the conversation's total turn count (Wave 1 has no
per-turn "resolution" flag on the trace itself; the whole trace IS one
resolution attempt, so its turn count is the number that gets compared).
`intent baseline` is `Baselines.per_intent[trace.trace.conversation.
scenario_id]` (PRD §5's `Baselines`/`IntentBaseline` contract). A scenario_id
with no baseline entry cannot be evaluated -- this detector is silent for it
rather than guessing a threshold (see `fixtures/sample/baselines.json` and its
calibration note in the Wave report for which scenario_ids are covered).

Waste calculation (verbatim): `(turns − p50_turns) × mean_cost_per_turn`.
Uses the baseline's own `mean_cost_per_turn` (not this conversation's actual
average), per the PRD formula -- the excess-turn COUNT comes from this trace,
the per-turn COST comes from the calibrated baseline.
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict

TURN_INFLATION_CONFIDENCE = 0.85  # baseline-derived (statistical), not a bare structural match.


def detect_turn_inflation(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    scenario_id = trace.trace.conversation.scenario_id
    baseline = baselines.per_intent.get(scenario_id)
    if baseline is None:
        return []

    turns = trace.trace.turns
    turns_to_resolution = len(turns)
    if turns_to_resolution <= baseline.p75_turns:
        return []

    waste = (turns_to_resolution - baseline.p50_turns) * baseline.mean_cost_per_turn
    if waste <= 0:
        return []

    last_turn = turns[-1]
    span_id = last_turn.llm[-1].span_id if last_turn.llm else f"turn{last_turn.turn_index}:inflation"

    return [
        Finding(
            class_id=4,
            turn_index=last_turn.turn_index,
            span_id=span_id,
            waste_usd=waste,
            confidence=TURN_INFLATION_CONFIDENCE,
            proposed_variant=VariantSpec(context_strategy="summarize:2000"),
            evidence={
                "scenario_id": scenario_id,
                "turns_to_resolution": turns_to_resolution,
                "p50_turns": baseline.p50_turns,
                "p75_turns": baseline.p75_turns,
                "mean_cost_per_turn": baseline.mean_cost_per_turn,
            },
        )
    ]
