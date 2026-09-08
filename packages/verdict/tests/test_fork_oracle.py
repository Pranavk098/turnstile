"""Wave-2 preservation-under-divergence oracle (TDD -- written FIRST, red).

The oracle judges a FORKED decision against the trace's ground-truth intent
via ``turnstile_verdict.registry`` semantics -- deliberately NEVER by
re-adjudicating the fork through pinned downstream tools (that judges a trace
that never happened: a fiction). Every rule is stated in the oracle's
docstring; the two modeling constants are sweepable here.

Fixture-driven cases live in fixtures/forks/*.json (authored ground truth, a
NEW dir -- fixtures/golden/ and fixtures/preservation/ are untouched). Each
case asserts the oracle's verdict exactly, including explicit ``null``
(undecidable) cases: a registry-undecidable fork is an honest None, never a
guess.
"""
from __future__ import annotations

import json
from pathlib import Path

from turnstile_schema.enums import DecisionKind

from turnstile_verdict.fork_oracle import (
    ASSUME_ESCALATION_COMMITS,
    FORKED_MUTATION_ATTEMPT_SERVES_INTENT,
    Decision,
    preserved_under_divergence,
)

FORKS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "forks"


def _d(kind: DecisionKind, label: str) -> Decision:
    return Decision(kind=kind, label=label)


# --------------------------------------------------------------------------- #
# route forks: registry-decidable cross-intent, None otherwise.               #
# --------------------------------------------------------------------------- #

def test_route_fork_to_incompatible_registered_scenario_is_not_preserved():
    verdict = preserved_under_divergence(
        "cancel_subscription",
        _d(DecisionKind.route, "cancel_subscription"),
        _d(DecisionKind.route, "refund"),
    )
    assert verdict is False


def test_route_fork_from_lookup_intent_to_mutation_intent_is_not_preserved():
    verdict = preserved_under_divergence(
        "order_status",
        _d(DecisionKind.route, "order_status"),
        _d(DecisionKind.route, "cancel_subscription"),
    )
    assert verdict is False


def test_route_fork_to_another_registered_scenario_is_decidable():
    """Corpus route-candidate enrichment (all SCENARIOS ids + "other") means a
    fork can land on a registered alternative: order_status (lookup,
    requires_mutation None) -> refund (mutation, requires process_refund) has
    incompatible requirements, so the oracle decides False -- never None.
    This is the fork shape the enriched corpus unblocks."""
    verdict = preserved_under_divergence(
        "order_status",
        _d(DecisionKind.route, "order_status"),
        _d(DecisionKind.route, "refund"),
    )
    assert verdict is False


def test_route_fork_to_same_requirement_scenario_serves_the_intent():
    """Stated rule: two registered scenarios with the SAME registry-required
    mutation provide the intent's requirement either way (no such pair exists
    in the registry today; the rule is stated + tested, not exercised)."""
    verdict = preserved_under_divergence(
        "cancel_subscription",
        _d(DecisionKind.route, "cancel_subscription"),
        _d(DecisionKind.route, "cancel_subscription"),
    )
    assert verdict is True  # identity branch, not the same-requirement rule


def test_route_fork_to_other_is_undecidable():
    """No registry entry for "other": an honest None, never a guess. (The
    candidate rule "non-resolution -> not preserved" needs owner ratification
    and is NOT assumed here.)"""
    verdict = preserved_under_divergence(
        "cancel_subscription",
        _d(DecisionKind.route, "cancel_subscription"),
        _d(DecisionKind.route, "other"),
    )
    assert verdict is None


def test_route_fork_with_unparseable_label_is_undecidable():
    verdict = preserved_under_divergence(
        "cancel_subscription",
        _d(DecisionKind.route, "cancel_subscription"),
        _d(DecisionKind.route, "I will take care of that for you right away."),
    )
    assert verdict is None


def test_route_fork_with_unregistered_intent_is_undecidable():
    """The registry carries no claim for an unknown scenario_id."""
    verdict = preserved_under_divergence(
        "not_a_real_scenario",
        _d(DecisionKind.route, "not_a_real_scenario"),
        _d(DecisionKind.route, "refund"),
    )
    assert verdict is None


# --------------------------------------------------------------------------- #
# escalate_check forks: escalation is intent-agnostic resolution (assumption  #
# stated + sweepable); dropping the handoff is undecidable without open-loop. #
# --------------------------------------------------------------------------- #

def test_escalate_fork_continue_to_escalate_is_preserved_under_default_assumption():
    verdict = preserved_under_divergence(
        "cancel_subscription",
        _d(DecisionKind.escalate_check, "continue"),
        _d(DecisionKind.escalate_check, "escalate"),
    )
    assert verdict is (True if ASSUME_ESCALATION_COMMITS else None)


def test_escalation_assumption_is_sweepable():
    """Sweep ASSUME_ESCALATION_COMMITS to False: the escalate fork loses its
    stated grounding and degrades to None (no silent claim)."""
    import turnstile_verdict.fork_oracle as fo

    original = fo.ASSUME_ESCALATION_COMMITS
    try:
        fo.ASSUME_ESCALATION_COMMITS = False
        verdict = preserved_under_divergence(
            "cancel_subscription",
            _d(DecisionKind.escalate_check, "continue"),
            _d(DecisionKind.escalate_check, "escalate"),
        )
        assert verdict is None
    finally:
        fo.ASSUME_ESCALATION_COMMITS = original


def test_escalate_fork_escalate_to_continue_is_undecidable():
    """Dropping a handoff: whether the scenario's own path would still resolve
    depends on unpinned downstream -- None, not a guess."""
    verdict = preserved_under_divergence(
        "cancel_subscription",
        _d(DecisionKind.escalate_check, "escalate"),
        _d(DecisionKind.escalate_check, "continue"),
    )
    assert verdict is None


# --------------------------------------------------------------------------- #
# tool_select forks: decidable only where the registry names the tool.        #
# --------------------------------------------------------------------------- #

def test_tool_select_fork_to_the_registry_required_tool_serves_the_intent():
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.tool_select, "lookup_account"),
        _d(DecisionKind.tool_select, "process_refund"),
    )
    assert verdict is True


def test_tool_select_fork_dropping_the_registry_required_tool_is_not_preserved():
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.tool_select, "process_refund"),
        _d(DecisionKind.tool_select, "lookup_account"),
    )
    assert verdict is False


def test_tool_select_fork_engaging_no_registry_requirement_is_undecidable():
    """Neither tool is the registry-required one (lookup intent): the fork
    does not engage the requirement either way -> None."""
    verdict = preserved_under_divergence(
        "order_status",
        _d(DecisionKind.tool_select, "retrieve_kb_article"),
        _d(DecisionKind.tool_select, "lookup_account"),
    )
    assert verdict is None


# --------------------------------------------------------------------------- #
# compose forks: the registry-required terminal act is the decision channel.  #
# --------------------------------------------------------------------------- #

def test_compose_fork_dropping_the_required_terminal_act_is_not_preserved():
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.compose, "complete_mutation"),
        _d(DecisionKind.compose, "inform"),
    )
    assert verdict is False


def test_compose_fork_attempting_the_required_terminal_act_serves_the_intent():
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.compose, "inform"),
        _d(DecisionKind.compose, "complete_mutation"),
    )
    assert verdict is (True if FORKED_MUTATION_ATTEMPT_SERVES_INTENT else None)


def test_mutation_attempt_assumption_is_sweepable():
    import turnstile_verdict.fork_oracle as fo

    original = fo.FORKED_MUTATION_ATTEMPT_SERVES_INTENT
    try:
        fo.FORKED_MUTATION_ATTEMPT_SERVES_INTENT = False
        verdict = preserved_under_divergence(
            "refund",
            _d(DecisionKind.compose, "inform"),
            _d(DecisionKind.compose, "complete_mutation"),
        )
        assert verdict is None
    finally:
        fo.FORKED_MUTATION_ATTEMPT_SERVES_INTENT = original


def test_compose_fork_engaging_no_terminal_act_on_mutation_intent_is_undecidable():
    """Neither side is complete_mutation (mid-flow utterances): the registry
    requirement is not decided by this fork -> None."""
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.compose, "inform"),
        _d(DecisionKind.compose, "close_call"),
    )
    assert verdict is None


def test_compose_fork_on_lookup_intent_is_undecidable():
    """A lookup intent carries no registry requirement, and informational
    resolution rides on utterance CONTENT (adjudicator's clean-close) -- not
    decidable from a label -> None."""
    verdict = preserved_under_divergence(
        "order_status",
        _d(DecisionKind.compose, "inform"),
        _d(DecisionKind.compose, "close_call"),
    )
    assert verdict is None


# --------------------------------------------------------------------------- #
# Identity is trivially preserved; slot_fill is content-driven -> None.       #
# --------------------------------------------------------------------------- #

def test_identity_fork_is_preserved():
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.slot_fill, "request_slot"),
        _d(DecisionKind.slot_fill, "request_slot"),
    )
    assert verdict is True


def test_slot_fill_fork_is_undecidable():
    """slot_fill's verdict rides on utterance content (clean-close), not the
    single label -- label-level judgment is vacuous -> None."""
    verdict = preserved_under_divergence(
        "refund",
        _d(DecisionKind.slot_fill, "request_slot"),
        _d(DecisionKind.slot_fill, "some-other-utterance-label"),
    )
    assert verdict is None


# --------------------------------------------------------------------------- #
# Authored fixtures (fixtures/forks/*.json): ground truth asserted exactly.   #
# --------------------------------------------------------------------------- #

def test_authored_fork_fixtures_assert_the_oracle():
    """Every fixture carries an unambiguous ground-truth outcome (bool) or an
    explicit null (undecidable); the oracle must reproduce it exactly."""
    paths = sorted(FORKS_DIR.glob("*.json"))
    assert len(paths) >= 8  # every decidable kind + multiple undecidable cases
    for path in paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        verdict = preserved_under_divergence(
            case["intent"],
            Decision(kind=DecisionKind(case["original"]["kind"]),
                     label=case["original"]["label"]),
            Decision(kind=DecisionKind(case["forked"]["kind"]),
                     label=case["forked"]["label"]),
        )
        assert verdict == case["expected"], (
            f"{path.name}: oracle={verdict!r} expected={case['expected']!r} "
            f"({case.get('rule', '')})"
        )


def test_fixtures_include_an_explicitly_undecidable_case():
    """The brief's required None case, asserted from the fixtures themselves."""
    cases = [json.loads(p.read_text(encoding="utf-8"))
             for p in FORKS_DIR.glob("*.json")]
    assert any(case["expected"] is None for case in cases), (
        "fixtures/forks must include at least one explicitly-undecidable case"
    )
