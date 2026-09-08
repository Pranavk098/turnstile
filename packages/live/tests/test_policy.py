"""Policy unit tests: the mock decision policy is a pure function of
(scenario, caller text, turn index) -- deterministic, keyword-driven, no LLM,
no network, no clock."""
from __future__ import annotations

from turnstile_live.policy import decide


def test_route_classifies_billing_cues():
    action = decide("billing_dispute", "Hi, I was charged twice on my bill.", 0)
    assert action.decision_kind == "route"
    assert action.decision == "billing_dispute"
    assert action.reply


def test_route_classifies_refund_cues():
    action = decide("refund", "I want my money back for order 7.", 0)
    assert (action.decision_kind, action.decision) == ("route", "refund")


def test_route_falls_back_to_other_without_cues():
    action = decide("order_status", "Hello?", 0)
    assert (action.decision_kind, action.decision) == ("route", "other")


def test_tool_cues_request_a_lookup():
    action = decide("billing_dispute", "It is order ORD-4481, the August bill.", 1)
    assert action.decision_kind == "tool_select"
    assert action.tool == "lookup_invoices"


def test_thanks_close_the_call():
    action = decide("billing_dispute", "Thanks, that is all. Bye!", 2)
    assert (action.decision_kind, action.decision) == ("compose", "close_call")


def test_escalation_cues_escalate():
    action = decide("refund", "Let me talk to a human supervisor.", 1)
    assert (action.decision_kind, action.decision) == ("escalate_check", "escalate")


def test_policy_is_deterministic():
    first = decide("refund", "Where is my refund?", 0)
    second = decide("refund", "Where is my refund?", 0)
    assert first == second
