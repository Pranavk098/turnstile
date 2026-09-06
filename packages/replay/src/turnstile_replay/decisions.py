"""Decision parsing shared by the replay gate and the backends (Wave-2).

Single source of `parse_decision_chosen`: relocated verbatim from
`turnstile_experiments.openai_backend` (which now re-imports it -- experiments
depends on replay, not the reverse, so the dependency direction is preserved).
The kind-aware divergence gate (`turnstile_replay.replay`) and the real
backend MUST parse identically, hence one implementation.

`BOUNDED_LABEL_KINDS` names the decision kinds whose vocabulary is bounded
(each span's `decision_candidates`): the gate compares the replayed decision's
parsed label against the original span's recorded label for these kinds.
`slot_fill` is deliberately absent -- single-label, and its verdict rides on
utterance content, so it keeps the content/similarity divergence path.
"""
from __future__ import annotations

from turnstile_schema.enums import DecisionKind

# Containment keyword lists for escalate_check, stated constants with the
# same convention as the verdict layer's heuristics; full calibration was
# Wave-1's M-2 work.
ESCALATE_CONTAINMENT_MARKERS = (
    "escalate", "escalating", "transfer", "transferring", "specialist",
    "supervisor", "human agent", "connect you", "connecting you",
)
CONTINUE_CONTAINMENT_MARKERS = (
    "continue", "keep looking", "looking into", "still working",
    "one moment", "let me check",
)

# Bounded-vocab decision kinds: label equality is a meaningful gate signal.
BOUNDED_LABEL_KINDS: frozenset[DecisionKind] = frozenset({
    DecisionKind.route,
    DecisionKind.tool_select,
    DecisionKind.escalate_check,
    DecisionKind.compose,
})


def parse_decision_chosen(
    decision_kind: DecisionKind, text: str, candidates: list[str]
) -> str:
    """Parse the raw completion utterance into a `decision_chosen` value for
    the decision's kind (M-2):

    * ``escalate_check`` -> ``"escalate"``/``"continue"`` by containment: any
      ESCALATE_CONTAINMENT_MARKERS hit wins (escalation is the load-bearing
      signal), otherwise ``"continue"`` -- the conservative default, since
      claiming escalation has consequences. (Neither the utterance nor the
      corpus's own escalate texts necessarily contain the literal decision
      verbs -- "I'm connecting you with a specialist now." contains neither
      "escalate" nor "continue" -- hence the marker lists.)
    * ``tool_select`` / ``route`` / ``compose`` -> the longest of the original
      span's ``decision_candidates`` contained in the utterance (most specific
      wins; candidates are the valid labels, e.g. ``retrieve_kb_article``).
      When NO candidate is contained, the raw text passes through -- a choice
      is never fabricated. Underscored labels never occur in natural prose, so
      an unelicited reply abstains rather than guessing.
    * every other kind (``slot_fill``) -> documented passthrough (the raw
      text): single-label ``["request_slot"]`` carries no discriminating
      signal (value-level treatment is Wave-2 Item 2's open edge).
    """
    low = text.lower()
    if decision_kind is DecisionKind.escalate_check:
        if any(marker in low for marker in ESCALATE_CONTAINMENT_MARKERS):
            return "escalate"
        return "continue"
    if decision_kind in (DecisionKind.tool_select, DecisionKind.route, DecisionKind.compose):
        matches = [c for c in candidates if c.lower() in low]
        if matches:
            return max(matches, key=len)
        return text
    return text
