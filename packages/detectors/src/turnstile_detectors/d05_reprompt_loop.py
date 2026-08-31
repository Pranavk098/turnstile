"""Detector 5 -- Reprompt loop (PRD §6, row 5).

Detection rule (verbatim): "≥2 `llm.decide` with the same `decision_kind`
targeting the same slot (`decision_chosen`), in consecutive turns, with no
successful fill between."

Scope narrowing (beyond the literal rule, to hold the false-positive gate --
same precedent as d06_dead_tokens.py's `decision_kind == compose` narrowing):
restricted to `decision_kind == slot_fill`. The PRD's own wording --
"targeting the same slot" -- is slot-filling language; a `compose` decision
that happens to repeat its `decision_chosen` label across consecutive turns
(fixture 11_multi_waste_a turns 1-4 all carry `decision_chosen="handle_billing"`
as they narrate the same ongoing billing response, which is that fixture's
Detector-2 context-bloat setup, not a reprompt) is not "the same slot" in any
scenario sense -- it is a compose step continuing the same topic. Restricting
to `slot_fill` is the only reading that fires on 05_reprompt_loop and
13_multi_waste_c (both slot_fill) while staying silent on 11 (route/compose
only).

"Consecutive turns" is read as adjacent `turn_index` (i, i+1); adjacency
itself is what makes "no successful fill between" trivially satisfied (there
is no turn between two adjacent ones for a fill to have happened in). Only the
FIRST such adjacent repeat in the conversation is reported -- neither golden
fixture has more than one independent reprompt episode, and PRD §6 does not
specify how to aggregate multiple simultaneous loops.

Waste calculation (verbatim): "cost of all turns after the first reprompt".
Read as: the reprompt turn itself (the second, repeated `llm.decide` -- the
turn where the caller had to be asked again) plus every turn after it through
the end of the conversation, inclusive -- the redundant ask is itself wasted
work, not merely a marker of where waste starts.
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.enums import DecisionKind

REPROMPT_LOOP_CONFIDENCE = 0.95  # exact structural match (decision_kind + decision_chosen equality).


def detect_reprompt_loop(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    turns = trace.trace.turns

    def slot_fill_choice(turn):
        for span in turn.llm:
            if span.decision_kind is DecisionKind.slot_fill:
                return span
        return None

    for i in range(len(turns) - 1):
        first = slot_fill_choice(turns[i])
        second = slot_fill_choice(turns[i + 1])
        if first is None or second is None:
            continue
        if first.decision_chosen != second.decision_chosen:
            continue

        reprompt_turn = turns[i + 1]
        waste = sum(trace.turn_costs[i + 1:])
        if waste <= 0:
            return []

        return [
            Finding(
                class_id=5,
                turn_index=reprompt_turn.turn_index,
                span_id=second.span_id,
                waste_usd=waste,
                confidence=REPROMPT_LOOP_CONFIDENCE,
                proposed_variant=VariantSpec(model_routing={"slot_fill": "gpt-5-nano"}),
                evidence={
                    "decision_kind": DecisionKind.slot_fill.value,
                    "decision_chosen": second.decision_chosen,
                    "first_turn": turns[i].turn_index,
                    "reprompt_turn": reprompt_turn.turn_index,
                },
            )
        ]

    return []
