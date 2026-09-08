"""Mock decision policy: a pure function of (scenario, caller text, turn).

Keyword-driven and fully deterministic -- the Phase-1 stand-in for the LLM
(Phase 2 puts a real model behind the owner-gated flag; this module never
makes a network call). Turn 0 routes by intent cues; later turns handle
escalation, closing, tool lookups, and generic informing, in that priority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentAction:
    """One agent decision: what the loop records as the turn's llm block
    (plus an optional mock-tool run)."""

    decision_kind: str
    decision: str
    reply: str
    tool: str | None = None
    tool_kind: str | None = None
    tool_effect: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)


_ROUTE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("billing_dispute", ("bill", "charg", "invoice")),
    ("refund", ("refund", "money back")),
    ("order_status", ("order", "package", "deliver", "tracking")),
    ("cancel_subscription", ("cancel",)),
    ("appointment_reschedule", ("appointment", "reschedul", "book")),
    ("tech_support", ("password", "internet", "wifi", "technic", "support")),
)

_ESCALATE_CUES = ("human", "supervisor", "manager", "real person")
_CLOSE_CUES = ("thank", "bye", "that's all", "that is all")
_TOOL_CUES = ("ord-", "order", "account", "bill", "invoice")


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def decide(scenario: str, caller_text: str, turn_index: int) -> AgentAction:
    """Decide the agent's move. `scenario` is currently informational (the
    route classifier reads the caller text, like the corpus's own routing) --
    it is kept in the signature for the Phase-2 LLM policy, which will need
    it for prompting."""
    low = caller_text.lower()
    if turn_index == 0:
        for decision, cues in _ROUTE_CUES:
            if _contains_any(low, cues):
                return AgentAction(
                    decision_kind="route", decision=decision,
                    reply="Thanks — let me look into that for you.",
                )
        return AgentAction(
            decision_kind="route", decision="other",
            reply="Thanks — let me look into that for you.",
        )
    if _contains_any(low, _ESCALATE_CUES):
        return AgentAction(
            decision_kind="escalate_check", decision="escalate",
            reply="Understood — connecting you to a specialist now.",
            tool="transfer_to_agent", tool_kind="handoff",
            tool_effect="committed",
        )
    if _contains_any(low, _CLOSE_CUES):
        return AgentAction(
            decision_kind="compose", decision="close_call",
            reply="Glad I could help — is there anything else I can do for you today?",
        )
    if _contains_any(low, _TOOL_CUES):
        return AgentAction(
            decision_kind="tool_select", decision="lookup_invoices",
            reply="Let me pull up the records for that.",
            tool="lookup_invoices", tool_kind="lookup", tool_effect="none",
        )
    return AgentAction(
        decision_kind="compose", decision="inform",
        reply="Understood — let me look into that for you.",
    )
