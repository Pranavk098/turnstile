"""Detector 9 -- Escalation debt (PRD §6, row 9; schema v1.1 amendment).

Two independent tiers, mutually exclusive in practice: `adjudicate()`'s own
v1.1 rules mean a conversation reaches `ESCALATED` only via a `committed`
handoff and reaches a `rejected` terminal handoff only via `UNRESOLVED` --
never both -- so tier 1 and tier 2 never co-fire on the same trace.

Tier 1 (verbatim): "`verdict.label == ESCALATED` AND escalation was
predictable at an early turn t before the handoff." This wave has no live
escalation classifier, so per the wave brief `t = verdict.turn_of_no_return`
(no re-adjudication -- the `verdict` argument `detect()` already receives is
used as-is). Waste = "full cost of turns t..end", read as
`sum(turn_costs[t:])` inclusive.

KNOWN WEAKNESS (flagged, not silently accepted -- see the Wave report's
concerns section): Wave 1's `adjudicate()` sets `turn_of_no_return` for an
ESCALATED verdict to the turn of the terminal (committed) handoff span itself
(`turnstile_verdict.adjudicate._adjudicate_handoff`), not to any earlier
turn where escalation intent first became visible (e.g. an `escalate_check`
decision several turns before the actual transfer). Every golden ESCALATED
fixture's only mutating/handoff span IS its last turn, so `t` always equals
the conversation's own last turn and tier 1's "turns t..end" collapses to
that single terminal turn -- `09_escalation_debt`'s fixture narrative
("predictable at turn 3, ran 9 more turns") is not actually recovered by this
tier's dollar figure under the current verdict layer. This detector still
fires (a positive, if understated, waste figure) per its literal spec; a real
`t` requires a Wave-2 escalation classifier or a richer `turn_of_no_return`
in `verdict/`, both out of this package's scope.

Tier 2 (verbatim, schema v1.1 amendment): "spend before a handoff that then
FAILED (`handoff.effect = rejected`)". Because a rejected handoff routes
`adjudicate()` to `UNRESOLVED` rather than `ESCALATED`, this tier is checked
independently of `verdict.label` -- directly against the trace's own terminal
`tool_kind=handoff` span (mirroring, not importing, `turnstile_verdict.
adjudicate._terminal_mutation`'s "last mutating/handoff span in document
order" convention). Waste = the FULL conversation cost (`trace.conv_cost`),
flagged `evidence["tier"] = 2` -- "the most damning number the tool can
produce" per the amendment, since the caller paid for the whole call and was
still stranded.
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.enums import Effect, ToolKind, VerdictLabel

ESCALATION_DEBT_VARIANT = VariantSpec(escalation_policy="threshold:0.85")

# Tier 1 rests entirely on a Wave-1 stand-in (verdict.turn_of_no_return, itself
# just the terminal handoff's own turn -- see module docstring) for what should
# be a live escalation classifier; tier 2 is an exact, deterministic read of
# `effect == rejected` off the trace. Confidence reflects that gap.
ESCALATION_DEBT_TIER1_CONFIDENCE = 0.5
ESCALATION_DEBT_TIER2_CONFIDENCE = 0.95


def _terminal_handoff(trace: PricedTrace):
    handoff = None
    for turn in trace.trace.turns:
        for tool in turn.tools:
            if tool.tool_kind is ToolKind.handoff:
                handoff = (turn.turn_index, tool)
    return handoff


def detect_escalation_debt(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    findings: list[Finding] = []
    turns = trace.trace.turns

    # -- Tier 1: predictable-but-delayed escalation -----------------------------
    if verdict.label is VerdictLabel.ESCALATED and verdict.turn_of_no_return is not None:
        t = verdict.turn_of_no_return
        t_pos = next((i for i, turn in enumerate(turns) if turn.turn_index == t), None)
        if t_pos is not None:
            waste = sum(trace.turn_costs[t_pos:])
            if waste > 0:
                anchor_turn = turns[t_pos]
                span_id = anchor_turn.llm[-1].span_id if anchor_turn.llm else f"turn{t}:escalation_debt"
                findings.append(
                    Finding(
                        class_id=9,
                        turn_index=t,
                        span_id=span_id,
                        waste_usd=waste,
                        confidence=ESCALATION_DEBT_TIER1_CONFIDENCE,
                        proposed_variant=ESCALATION_DEBT_VARIANT,
                        evidence={
                            "tier": 1,
                            "turn_of_no_return": t,
                            "conversation_end_turn": turns[-1].turn_index,
                            "note": "t is verdict.turn_of_no_return (Wave-1 stand-in for a live "
                                     "escalation classifier; see module docstring's KNOWN WEAKNESS).",
                        },
                    )
                )

    # -- Tier 2: spend before a handoff that then failed -------------------------
    terminal = _terminal_handoff(trace)
    if terminal is not None:
        turn_idx, tool = terminal
        if tool.effect is Effect.rejected:
            findings.append(
                Finding(
                    class_id=9,
                    turn_index=turn_idx,
                    span_id=tool.span_id,
                    waste_usd=trace.conv_cost,
                    confidence=ESCALATION_DEBT_TIER2_CONFIDENCE,
                    proposed_variant=ESCALATION_DEBT_VARIANT,
                    evidence={
                        "tier": 2,
                        "tool_name": tool.tool_name,
                        "effect": tool.effect.value,
                        "conv_cost_usd": trace.conv_cost,
                        "note": "terminal handoff rejected -- caller stranded after paying "
                                 "full conversation cost.",
                    },
                )
            )

    return findings
