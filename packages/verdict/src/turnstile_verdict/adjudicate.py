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
    The assertion is BOUND TO INTENT (Section B3): the final utterance must
    contain a completion keyword AND reference an intent token parsed from
    the scenario_id / terminal tool_name (Wave-1 stand-in for the scenario
    registry; with no derivable intent tokens FALSE_RESOLVE is never claimed).
  - unknown blocks confident verdicts: any required mutation at ``effect ==
    unknown`` caps confidence at 0.6, forbids RESOLVED/FALSE_RESOLVE, and records
    the ambiguity in evidence.
  - ESCALATED requires ``handoff.effect == committed``; a rejected handoff ->
    UNRESOLVED, a pending handoff -> UNRESOLVED (not yet ESCALATED).
  - Section C2 (GAP-11) via the minimal scenario registry
    (``turnstile_verdict.registry``): MISROUTED when a committed mutation is
    not the scenario's required tool (or the scenario requires no mutation);
    PARTIALLY_RESOLVED when the registry-matched required mutation is present
    but pending (attempted, not committed). Unregistered scenarios keep the
    pre-registry behavior exactly.

``turn_of_no_return`` for ESCALATED (GAP-05, PRD Sec.6 D9): PRD Sec.7 defines
it as "the earliest turn at which the final verdict was already determined."
For an ESCALATED verdict this wave has no live escalation classifier (PRD
Sec.6 D9's "escalation classifier >= 0.9 at turn t"), so
``_earliest_escalate_check`` is used as a deterministic Wave-1 stand-in: the
earliest turn containing an ``llm.decide`` span with
``decision_kind == escalate_check``. If no such span exists, this falls back
to the handoff's own turn (the pre-fix behavior). The real classifier is
Wave-2/3 work. This only changes ``turn_of_no_return`` -- it never changes
the verdict LABEL.
"""
from __future__ import annotations

import re

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

from turnstile_verdict.registry import lookup

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

# Section C2 (GAP-11): the two labels the registry makes emitable.
CONF_MISROUTED = 0.85               # deterministic: committed tool != registry's required tool
CONF_PARTIALLY_RESOLVED = 0.75      # registry-matched mutation attempted (pending), not committed

# Binding v1.1: any required mutation at effect=unknown caps confidence here and
# forbids RESOLVED / FALSE_RESOLVE.
UNKNOWN_CONFIDENCE_CAP = 0.60

# End reasons that mean the call did NOT finish normally. On the informational
# path (no required mutation/handoff) a non-clean end forbids the default
# "intent was served" RESOLVED: the conversation may have ended before the
# intent was actually handled. Matches the doc's non-clean set exactly
# (timeout / error / agent_hangup); caller_hangup is the caller's choice and
# remains a legitimate informational close.
NON_CLEAN_END_REASONS = frozenset(
    {EndReason.timeout, EndReason.error, EndReason.agent_hangup}
)

# Source 3 search window: caller-confirmation / clean-close utterance is looked
# for in the final N turns.
CONFIRMATION_WINDOW_TURNS = 2

# "Agent asserts completion" heuristic (drives FALSE_RESOLVE). Case-insensitive
# substring match against the agent's final output_text -- BOUND TO THE SCENARIO
# INTENT (Section B3): a keyword hit alone is not an assertion of THE INTENT's
# completion; the utterance must also reference an intent token (parsed from the
# scenario_id / terminal mutation's tool_name, see _intent_terms). Wave-2
# refinement: replace with a scenario-registry-aware completion classifier.
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


def _earliest_escalate_check(trace: Trace) -> int | None:
    """Earliest turn containing an ``llm.decide`` span with
    ``decision_kind == escalate_check``, if any.

    Wave-1 deterministic stand-in for PRD Sec.6 D9's "escalation classifier
    >= 0.9 at turn t" (GAP-05). The real classifier is Wave-2/3; this proxy
    lets ESCALATED verdicts' ``turn_of_no_return`` reflect the turn escalation
    became predictable rather than only the turn of the eventual handoff.
    """
    for turn in trace.turns:
        for llm in turn.llm:
            if llm.decision_kind is DecisionKind.escalate_check:
                return turn.turn_index
    return None


def _intent_terms(scenario_id: str | None, tool_name: str | None) -> frozenset[str]:
    """The intent's identifying tokens -- the Wave-1 deterministic stand-in
    for the scenario registry (Wave-2): parsed from the scenario_id and the
    terminal mutation's tool_name (split on non-alphanumerics; fragments
    under 4 chars dropped as noise). Both sources may be opaque, in which
    case the set is empty and no completion assertion can be bound."""
    terms: set[str] = set()
    for source in (scenario_id, tool_name):
        for token in re.split(r"[^a-z0-9]+", (source or "").lower()):
            if len(token) >= 4:
                terms.add(token)
    return frozenset(terms)


def _asserts_completion(text: str, intent_terms: frozenset[str]) -> bool:
    """Does the agent's utterance claim THE INTENT's task is done?
    (FALSE_RESOLVE trigger.)

    Bound to intent (Section B3): a completion keyword alone is not enough --
    an unbound free-substring match fired on cross-intent and incidental hits
    (e.g. 'the status has been updated' on a cancellation intent). The
    utterance must also reference one of the intent's tokens. If no intent
    tokens can be derived (opaque scenario_id AND tool_name), the assertion
    cannot be bound and is conservatively reported as False -- FALSE_RESOLVE
    is never claimed on an unbound keyword hit."""
    low = text.lower()
    if not any(kw in low for kw in COMPLETION_ASSERTION_KEYWORDS):
        return False
    return any(term in low for term in intent_terms)


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
            return _adjudicate_handoff(conv, t_turn, t_tool)

        # -- Mutation branch ---------------------------------------------------
        return _adjudicate_mutation(conv, t_turn, t_tool)

    # -- No mutation/handoff: informational intent. Fall to lower-precedence
    #    evidence (sources 2-4). ----------------------------------------------
    return _adjudicate_informational(conv)


def _adjudicate_handoff(trace: Trace, turn_idx: int, tool: ToolCall) -> Verdict:
    base = {
        "source": "terminal_tool_state",
        "tool_name": tool.tool_name,
        "tool_kind": "handoff",
        "effect": tool.effect.value,
        "tool_status": tool.tool_status.value,
        "turn_index": turn_idx,
    }
    if tool.effect is Effect.committed:
        # GAP-05 (PRD Sec.6 D9): turn_of_no_return is the earliest turn
        # escalation became predictable, not merely the handoff's own turn.
        # Wave-1 deterministic proxy: the earliest escalate_check decision, if
        # any (see _earliest_escalate_check); otherwise fall back to the
        # handoff turn (pre-fix behavior).
        escalate_turn = _earliest_escalate_check(trace)
        no_return = escalate_turn if escalate_turn is not None else turn_idx
        evidence_entry = {**base, "rule": "escalated_requires_handoff_committed"}
        if escalate_turn is not None:
            evidence_entry["turn_of_no_return_source"] = "earliest_escalate_check"
            evidence_entry["escalate_check_turn"] = escalate_turn
        else:
            evidence_entry["turn_of_no_return_source"] = "handoff_turn_fallback"
        return Verdict(
            label=VerdictLabel.ESCALATED,
            confidence=CONF_ESCALATED,
            evidence=[evidence_entry],
            turn_of_no_return=no_return,
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
    if not incomplete:
        # effect == committed: RESOLVED -- unless the registry says the
        # handled intent is not the scenario's intent (Section C2, MISROUTED),
        # or the scenario requires NO mutation at all.
        spec = lookup(trace.conversation.scenario_id)
        if spec is not None and tool.tool_name != spec.requires_mutation:
            return Verdict(
                label=VerdictLabel.MISROUTED,
                confidence=CONF_MISROUTED,
                evidence=[{
                    **base,
                    "rule": "handled_intent_mismatches_scenario",
                    "scenario_id": trace.conversation.scenario_id,
                    "handled_tool": tool.tool_name,
                    "required_tool": spec.requires_mutation,
                    "note": "mutation committed, but not the one the scenario's "
                            "intent requires (registry: turnstile_verdict.registry).",
                }],
                turn_of_no_return=turn_idx,
            )
        return Verdict(
            label=VerdictLabel.RESOLVED,
            confidence=CONF_RESOLVED_COMMITTED,
            evidence=[{**base, "rule": "resolved_requires_effect_committed"}],
            turn_of_no_return=turn_idx,
        )
    intent_terms = _intent_terms(trace.conversation.scenario_id, tool.tool_name)
    final = _final_llm(trace)
    asserts = final is not None and _asserts_completion(final[1].output_text, intent_terms)
    if asserts:
        # Deterministic FALSE_RESOLVE -- the most expensive failure.
        return Verdict(
            label=VerdictLabel.FALSE_RESOLVE,
            confidence=CONF_FALSE_RESOLVE,
            evidence=[{
                **base,
                "rule": "false_resolve_assertion_contradicts_effect",
                "asserts_completion": True,
                "bound_to_intent": sorted(intent_terms),
                "final_output_text": final[1].output_text,
                "note": "agent claimed completion of the intent but mutation "
                        "did not commit (assertion bound to intent tokens from "
                        "scenario_id/tool_name).",
            }],
            turn_of_no_return=turn_idx,
        )
    if tool.effect is Effect.pending:
        # Section C2 (GAP-11): the registry-matched required mutation was
        # ATTEMPTED but not committed -- some-but-not-all of the required
        # effects occurred. Rejected stays UNRESOLVED (a failed attempt, not
        # a partial one); an unregistered or wrong-tool pending mutation
        # stays UNRESOLVED (no partial claim without an intent match).
        spec = lookup(trace.conversation.scenario_id)
        if spec is not None and tool.tool_name == spec.requires_mutation:
            return Verdict(
                label=VerdictLabel.PARTIALLY_RESOLVED,
                confidence=CONF_PARTIALLY_RESOLVED,
                evidence=[{
                    **base,
                    "rule": "required_mutation_attempted_not_committed",
                    "scenario_id": trace.conversation.scenario_id,
                    "handled_tool": tool.tool_name,
                    "note": "the scenario's required mutation is present but "
                            "pending -- partially handled, not resolved.",
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

    # Non-clean end (timeout / error / agent_hangup): the call did not finish
    # normally, so the informational intent cannot be judged "served" -- even
    # with a clean-close utterance in the tail (a courtesy goodbye before a
    # timeout is still a timeout). Matching the binding-v1.1 unknown-handling
    # style: mark unknown, cap confidence, forbid RESOLVED, record the
    # ambiguity in evidence. (Placed after the ABANDONED branch, which requires
    # caller_hangup and is therefore disjoint from this guard.)
    if trace.conversation.end_reason in NON_CLEAN_END_REASONS:
        return Verdict(
            label=VerdictLabel.UNRESOLVED,
            confidence=UNKNOWN_CONFIDENCE_CAP,
            evidence=[{
                "source": "informational_resolution",
                "rule": "non_clean_end_blocks_informational_resolution",
                "end_reason": trace.conversation.end_reason.value,
                "clean_close": _has_clean_close(trace),
                "note": "informational intent (no required mutation/handoff) but "
                        "the call ended non-cleanly; declining to fabricate a "
                        "resolution. confidence capped, RESOLVED forbidden.",
            }],
            turn_of_no_return=None,
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
