"""The ground-truth INTENT oracle for preservation-under-divergence (Wave-2).

Question answered: when the cheaper model's replayed decision DIFFERS from the
original (a fork -- excluded from the measured identity-preservation figure by
the kind-aware gate), does the forked decision still serve the trace's true
intent? Judged from ``turnstile_verdict.registry`` semantics + the existing
adjudicator's resolution rules -- deliberately NEVER by re-adjudicating the
fork through pinned downstream tools (a fork judged against the original
trace's tool spans is a trace that never happened: a pinned-tool fiction, and
any such verdict is forbidden here).

This is a MODELED estimate on synthetic ground truth (Instrumented tier). It
is reported separately and is NEVER folded into the measured 0.985
identity-preservation number. The real measured number requires open-loop
execution of the divergent path -- deferred, out of scope, the honest ceiling.

Stated, sweepable modeling constants (no unstated modeling decisions):

* ``ASSUME_ESCALATION_COMMITS`` -- a forked ``continue -> escalate`` decision
  is judged preserved because escalation is intent-agnostic resolution (the
  adjudicator scores a committed handoff ESCALATED @ 0.90 for ANY scenario;
  no registry scenario excludes escalation). The assumption is that the
  forked path's handoff WOULD commit -- under open-loop that is not
  guaranteed, so with the constant False the fork degrades to None.
* ``FORKED_MUTATION_ATTEMPT_SERVES_INTENT`` -- a forked decision attempting
  the registry-required terminal act (``complete_mutation`` on a mutation
  intent) is judged preserved: the intent's requirement becomes reachable.
  The assumption is that the forked path's mutation would be the intent's own
  tool; with the constant False the fork degrades to None.

Undecidability is a first-class outcome: a registry-undecidable fork returns
``None`` -- never a guess. Registry entries are the ONLY intent claims; a
scenario absent from the registry carries no claim either way.
"""
from __future__ import annotations

from dataclasses import dataclass

from turnstile_schema.enums import DecisionKind

from turnstile_verdict.registry import lookup

# Modeling constants -- sweepable; see module docstring for grounding.
ASSUME_ESCALATION_COMMITS = True
FORKED_MUTATION_ATTEMPT_SERVES_INTENT = True

# The corpus's non-resolution route label: deliberately NOT registered, so a
# fork to "other" has no registry rule and returns None (a candidate rule
# "non-resolution -> not preserved" awaits owner ratification; it is NOT
# assumed here).
OTHER_ROUTE_LABEL = "other"


@dataclass(frozen=True)
class Decision:
    """A decision channel: the decision kind plus its parsed label."""

    kind: DecisionKind
    label: str


def preserved_under_divergence(
    trace_intent: str, original: Decision, forked: Decision
) -> bool | None:
    """Does the forked decision serve the trace's true intent?

    Returns True (preserved) / False (not preserved) / None (undecidable from
    the registry + adjudicator rules alone -- never a guess). Rules per kind:

    * Identity (same kind + label): trivially preserved.
    * Unregistered ``trace_intent``: the registry carries no claim -> None.
    * ``route``: the forked label is looked up in the registry.
        - Unregistered forked label ("other", raw passthrough): no registry
          rule -> None.
        - Registered fork with the SAME requirement as the intent: the
          requirement is provided either way -> True (stated rule; no such
          scenario pair exists today, kept for completeness).
        - Registered fork with a DIFFERENT requirement: the agent understood
          the call as another intent; the trace's requirement is not served
          -> False.
    * ``escalate_check``: escalation serves ANY intent (intent-agnostic
      resolution), under ``ASSUME_ESCALATION_COMMITS`` (else None);
      ``escalate -> continue`` drops the handoff and the forked outcome
      depends on unpinned downstream -> None.
    * ``tool_select``: decidable only against the registry-required tool --
      forked == required -> True; original == required, forked != required
      -> False; neither engages the requirement -> None.
    * ``compose``: on a mutation intent, the registry-required terminal act
      (``complete_mutation``) is the decision channel -- forked attempts it
      -> True under ``FORKED_MUTATION_ATTEMPT_SERVES_INTENT`` (else None);
      original attempts it and the fork drops it -> False; neither side is
      the terminal act (mid-flow utterances) -> None. On a lookup intent,
      resolution rides on utterance content, not the label -> None.
    * ``slot_fill`` and any other kind: single-label / content-driven -- a
      label-level judgment is vacuous -> None.
    """
    spec = lookup(trace_intent)
    if spec is None:
        return None  # the registry carries no claim for this scenario
    if forked.kind is original.kind and forked.label == original.label:
        return True  # identity: the same decision, trivially preserved

    if forked.kind is DecisionKind.route:
        forked_spec = lookup(forked.label)
        if forked_spec is None:
            return None  # "other" / unparseable: no registry rule
        if forked_spec.requires_mutation == spec.requires_mutation:
            return True  # same requirement: served either way (stated)
        return False  # incompatible requirement: intent not served

    if forked.kind is DecisionKind.escalate_check:
        if original.label == "continue" and forked.label == "escalate":
            return True if ASSUME_ESCALATION_COMMITS else None
        return None  # escalate->continue (and unknown labels): undecidable

    if forked.kind is DecisionKind.tool_select:
        required = spec.requires_mutation
        if required is not None and forked.label == required:
            return True  # the intent's required tool becomes the path
        if required is not None and original.label == required:
            return False  # the required tool was dropped
        return None  # neither decision engages the registry requirement

    if forked.kind is DecisionKind.compose:
        if spec.requires_mutation is None:
            return None  # lookup intent: content-driven resolution
        if forked.label == "complete_mutation":
            return True if FORKED_MUTATION_ATTEMPT_SERVES_INTENT else None
        if original.label == "complete_mutation":
            return False  # the required terminal act was dropped
        return None  # neither side is the terminal act (mid-flow)

    return None  # slot_fill / unbounded kinds: content-driven
