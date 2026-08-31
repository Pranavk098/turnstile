"""Resolution Ledger -- adjudicate whether a call was actually resolved.

Single entry point ``adjudicate(trace: PricedTrace) -> Verdict`` (PRD Sec.5/Sec.7,
schema v1.1 amendment). Reads the conversation/spans via ``trace.trace``; it does
NOT use costs -- outcome logic only.

Evidence precedence (PRD Sec.7, highest wins; the deciding source is recorded in
``Verdict.evidence``):

  1. Terminal tool state    -- deterministic; ``ToolCall.effect`` on the intent's
                               terminal required mutation/handoff. Strongest.
  2. Required-slot completion against the scenario. No scenario/slot registry
     exists in Wave 1, so this is APPROXIMATED from the trace (was the agent still
     soliciting a required slot when the call ended?). Wave-2 refinement: a real
     scenario registry names the required slots and the required terminal mutation.
  3. Caller-confirmation / clean-close utterance in the final two turns.
  4. Absence of an escalation span.
  5. LLM judgment -- lowest weight, tie-break only. Wave 1 implements this as a
     deterministic ABSTAIN stub (``_llm_judgment_stub``); NO live LLM/API call.

Binding v1.1 rules (schema v1.1 amendment, Sec. "Verdict-layer consequences"):
  - RESOLVED requires the terminal required mutation ``effect == committed``.
  - FALSE_RESOLVE: agent asserts completion AND terminal mutation
    ``effect in {pending, rejected}`` or ``tool_status == error``. Deterministic.
  - unknown blocks confident verdicts: any required mutation at ``effect ==
    unknown`` caps confidence at 0.6, forbids RESOLVED/FALSE_RESOLVE, and records
    the ambiguity in evidence.
  - ESCALATED requires ``handoff.effect == committed``; a rejected handoff ->
    UNRESOLVED, a pending handoff -> UNRESOLVED (not yet ESCALATED).
"""
from __future__ import annotations

from turnstile_schema import PricedTrace, Verdict
from turnstile_schema.enums import (
    DecisionKind,
    Effect,
    EndReason,
    ToolKind,
    ToolStatus,
    VerdictLabel,
)
from turnstile_schema.spans import LlmDecide, ToolCall
from turnstile_schema.trace import Trace

# --------------------------------------------------------------------------- #
# Named constants -- documented thresholds and keyword lists (never inline      #
# magic literals). Full calibration (60 hand labels, Cohen's kappa) is deferred #
# to the Wave-3 corpus; these are the fixed Wave-1 priors validated against the #
# 23 golden fixtures.                                                           #
# --------------------------------------------------------------------------- #

# Per-path confidence priors.
CONF_RESOLVED_COMMITTED = 0.90       # source 1: terminal mutation effect=committed
CONF_RESOLVED_INFORMATIONAL = 0.70   # no mutation; informational intent, sources 2-4
CONF_FALSE_RESOLVE = 0.90            # deterministic: assertion + non-committed effect
CONF_ESCALATED = 0.90               # handoff effect=committed
CONF_HANDOFF_REJECTED = 0.85        # handoff effect=rejected -> UNRESOLVED
CONF_HANDOFF_PENDING = 0.80         # handoff effect=pending -> not yet ESCALATED
CONF_MUTATION_INCOMPLETE = 0.80     # pending/rejected mutation, no completion claim
CONF_ABANDONED = 0.70               # caller hung up mid-slot-fill

# Binding v1.1: any required mutation at effect=unknown caps confidence here and
# forbids RESOLVED / FALSE_RESOLVE.
UNKNOWN_CONFIDENCE_CAP = 0.60

# Source 3 search window: caller-confirmation / clean-close utterance is looked
# for in the final N turns.
CONFIRMATION_WINDOW_TURNS = 2

# "Agent asserts completion" heuristic (drives FALSE_RESOLVE). Case-insensitive
# substring match against the agent's final output_text. Wave-2 refinement:
# replace with a scenario-aware completion classifier.
COMPLETION_ASSERTION_KEYWORDS = (
    "processed", "completed", "is complete", "all set", "done",
    "taken care of", "has been", "successfully", "refunded",
    "cancelled", "canceled", "updated", "confirmed", "booked", "scheduled",
    "you're all set", "you are all set",
)

# Clean-close utterance keywords (source 3, positive resolution signal) -- a
# caller_hangup after one of these is a satisfied close, not an abandonment.
CLOSING_KEYWORDS = (
    "goodbye", "bye", "anything else", "have a great", "take care",
    "you're all set", "glad i could help",
)

# Decision kinds meaning the agent was still gathering required input when the
# call ended (abandonment signal; source-2 slot-completion approximation).
SOLICITING_DECISION_KINDS = (DecisionKind.slot_fill,)

# The two tool kinds whose terminal state is verdict-load-bearing.
_MUTATING_KINDS = (ToolKind.mutation, ToolKind.handoff)


# --------------------------------------------------------------------------- #
# Trace-reading helpers                                                         #
# --------------------------------------------------------------------------- #

def _mutating_spans(trace: Trace) -> list[tuple[int, ToolCall]]:
    """(turn_index, ToolCall) for every mutation/handoff span, in document order."""
    out: list[tuple[int, ToolCall]] = []
    for turn in trace.turns:
        for tool in turn.tools:
            if tool.tool_kind in _MUTATING_KINDS:
                out.append((turn.turn_index, tool))
    return out


def _terminal_mutation(
    mutating: list[tuple[int, ToolCall]]
) -> tuple[int, ToolCall] | None:
    """The intent's terminal required mutation/handoff.

    Wave-1 approximation: the LAST mutating span in the trace. Wave-2 refinement:
    the scenario registry names the required terminal mutation explicitly rather
    than inferring it positionally.
    """
    return mutating[-1] if mutating else None


def _first_unknown(
    mutating: list[tuple[int, ToolCall]]
) -> tuple[int, ToolCall] | None:
    """The earliest required mutation whose effect is unknown, if any."""
    for turn_idx, tool in mutating:
        if tool.effect is Effect.unknown:
            return turn_idx, tool
    return None


def _final_llm(trace: Trace) -> tuple[int, LlmDecide] | None:
    """(turn_index, last llm.decide span) -- the agent's final utterance/decision."""
    found: tuple[int, LlmDecide] | None = None
    for turn in trace.turns:
        for llm in turn.llm:
            found = (turn.turn_index, llm)
    return found


def _asserts_completion(text: str) -> bool:
    """Does the agent's utterance claim the task is done? (FALSE_RESOLVE trigger)."""
    low = text.lower()
    return any(kw in low for kw in COMPLETION_ASSERTION_KEYWORDS)


def _has_clean_close(trace: Trace) -> bool:
    """Source 3: a clean-close / confirmation utterance in the final N turns."""
    tail = trace.turns[-CONFIRMATION_WINDOW_TURNS:]
    for turn in tail:
        for llm in turn.llm:
            low = llm.output_text.lower()
            if any(kw in low for kw in CLOSING_KEYWORDS):
                return True
    return False


def _llm_judgment_stub(trace: Trace) -> None:
    """Evidence source 5 (lowest weight, tie-break only).

    Wave 1 ABSTAINS -- no live LLM. This is the future hook where a calibrated
    LLM judge would return a (label, confidence) signal to break ties the
    deterministic sources leave open. It returns None (no signal) and is never
    consulted for a case the higher sources already decide.
    """
    return None


# --------------------------------------------------------------------------- #
# Entry point                                                                   #
# --------------------------------------------------------------------------- #

def adjudicate(trace: PricedTrace) -> Verdict:
    """Adjudicate resolution outcome from a PricedTrace (costs are not read)."""
    conv = trace.trace  # PricedTrace.trace is the underlying Trace
    mutating = _mutating_spans(conv)
    terminal = _terminal_mutation(mutating)

    # -- Evidence source 1: terminal tool state (deterministic, strongest) ----
    if terminal is not None:
        # Binding v1.1: unknown blocks confident verdicts. Checked FIRST so it
        # pre-empts both RESOLVED and FALSE_RESOLVE.
        unknown = _first_unknown(mutating)
        if unknown is not None:
            u_turn, u_tool = unknown
            evidence = [{
                "source": "terminal_tool_state",
                "rule": "unknown_blocks_confident_verdict",
                "tool_name": u_tool.tool_name,
                "tool_kind": u_tool.tool_kind.value,
                "effect": u_tool.effect.value,
                "tool_status": u_tool.tool_status.value,
                "turn_index": u_turn,
                "note": (
                    "required mutation effect=unknown -- outcome genuinely "
                    "ambiguous; declining to fabricate. confidence capped, "
                    "RESOLVED/FALSE_RESOLVE forbidden."
                ),
            }]
            return Verdict(
                label=VerdictLabel.UNRESOLVED,
                confidence=UNKNOWN_CONFIDENCE_CAP,
                evidence=evidence,
                turn_of_no_return=u_turn,
            )

        t_turn, t_tool = terminal

        # -- Handoff branch: ESCALATED requires effect=committed ---------------
        if t_tool.tool_kind is ToolKind.handoff:
            return _adjudicate_handoff(t_turn, t_tool)

        # -- Mutation branch ---------------------------------------------------
        return _adjudicate_mutation(conv, t_turn, t_tool)

    # -- No mutation/handoff: informational intent. Fall to lower-precedence
    #    evidence (sources 2-4). ----------------------------------------------
    return _adjudicate_informational(conv)


def _adjudicate_handoff(turn_idx: int, tool: ToolCall) -> Verdict:
    base = {
        "source": "terminal_tool_state",
        "tool_name": tool.tool_name,
        "tool_kind": "handoff",
        "effect": tool.effect.value,
        "tool_status": tool.tool_status.value,
        "turn_index": turn_idx,
    }
    if tool.effect is Effect.committed:
        return Verdict(
            label=VerdictLabel.ESCALATED,
            confidence=CONF_ESCALATED,
            evidence=[{**base, "rule": "escalated_requires_handoff_committed"}],
            turn_of_no_return=turn_idx,
        )
    if tool.effect is Effect.rejected:
        return Verdict(
            label=VerdictLabel.UNRESOLVED,
            confidence=CONF_HANDOFF_REJECTED,
            evidence=[{**base, "rule": "rejected_handoff_is_unresolved_not_escalated",
                       "note": "AI tried to hand off and could not; caller stranded."}],
            turn_of_no_return=turn_idx,
        )
    # pending: caller queued / still on hold -- not yet ESCALATED.
    return Verdict(
        label=VerdictLabel.UNRESOLVED,
        confidence=CONF_HANDOFF_PENDING,
        evidence=[{**base, "rule": "pending_handoff_not_yet_escalated",
                   "note": "caller queued/on hold; transfer not completed."}],
        turn_of_no_return=turn_idx,
    )


def _adjudicate_mutation(trace: Trace, turn_idx: int, tool: ToolCall) -> Verdict:
    base = {
        "source": "terminal_tool_state",
        "tool_name": tool.tool_name,
        "tool_kind": "mutation",
        "effect": tool.effect.value,
        "tool_status": tool.tool_status.value,
        "turn_index": turn_idx,
    }
    incomplete = (
        tool.effect in (Effect.pending, Effect.rejected)
        or tool.tool_status is ToolStatus.error
    )
    if incomplete:
        final = _final_llm(trace)
        asserts = final is not None and _asserts_completion(final[1].output_text)
        if asserts:
            # Deterministic FALSE_RESOLVE -- the most expensive failure.
            return Verdict(
                label=VerdictLabel.FALSE_RESOLVE,
                confidence=CONF_FALSE_RESOLVE,
                evidence=[{
                    **base,
                    "rule": "false_resolve_assertion_contradicts_effect",
                    "asserts_completion": True,
                    "final_output_text": final[1].output_text,
                    "note": "agent claimed completion but mutation did not commit.",
                }],
                turn_of_no_return=turn_idx,
            )
        # Mutation did not commit and the agent did not over-claim.
        return Verdict(
            label=VerdictLabel.UNRESOLVED,
            confidence=CONF_MUTATION_INCOMPLETE,
            evidence=[{**base, "rule": "mutation_not_committed",
                       "asserts_completion": False}],
            turn_of_no_return=turn_idx,
        )
    # effect == committed: RESOLVED.
    return Verdict(
        label=VerdictLabel.RESOLVED,
        confidence=CONF_RESOLVED_COMMITTED,
        evidence=[{**base, "rule": "resolved_requires_effect_committed"}],
        turn_of_no_return=turn_idx,
    )


def _adjudicate_informational(trace: Trace) -> Verdict:
    """No required mutation/handoff -- resolution rests on sources 2-4."""
    final = _final_llm(trace)
    caller_hangup = trace.conversation.end_reason is EndReason.caller_hangup

    # Source 2 (approx) + 3: caller hung up while the agent was still soliciting
    # a required slot, with no clean-close utterance -> ABANDONED.
    if caller_hangup and final is not None:
        _turn_idx, llm = final
        soliciting = llm.decision_kind in SOLICITING_DECISION_KINDS
        if soliciting and not _has_clean_close(trace):
            hangup_turn = trace.turns[-1].turn_index
            return Verdict(
                label=VerdictLabel.ABANDONED,
                confidence=CONF_ABANDONED,
                evidence=[{
                    "source": "slot_completion+caller_confirmation",
                    "rule": "caller_hangup_mid_slot_fill",
                    "end_reason": trace.conversation.end_reason.value,
                    "final_decision_kind": llm.decision_kind.value,
                    "final_output_text": llm.output_text,
                    "turn_index": _turn_idx,
                    "note": "caller hung up while agent was still gathering a "
                            "required slot; no terminal completion.",
                }],
                turn_of_no_return=hangup_turn,
            )

    # Otherwise the informational intent was served (source 4: no escalation
    # span; source 3: clean close where present). turn_of_no_return left None:
    # without a scenario registry the exact resolving turn is not derivable.
    evidence = [{
        "source": "informational_resolution",
        "rule": "no_required_mutation_intent_served",
        "end_reason": trace.conversation.end_reason.value,
        "clean_close": _has_clean_close(trace),
        "note": "no required mutation/handoff; informational intent. Wave-2 "
                "scenario registry needed to confirm required-slot completion.",
    }]
    return Verdict(
        label=VerdictLabel.RESOLVED,
        confidence=CONF_RESOLVED_INFORMATIONAL,
        evidence=evidence,
        turn_of_no_return=None,
    )
