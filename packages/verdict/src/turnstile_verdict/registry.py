"""Minimal scenario registry (GAP-11, Section C2 of the overnight batch doc).

Wave 1's verdict layer has no structured notion of "what the scenario
requires", which is why ``PARTIALLY_RESOLVED`` / ``MISROUTED`` were never
emitted. This registry is the minimal fix: ``scenario_id -> the tool the
intent requires`` (or ``None`` for lookup intents that require NO mutation).
Sources, in priority order:

* the corpus generator's own scenario table
  (``turnstile_corpus.distributions.SCENARIOS`` -- the authoritative
  scenario_id -> required tool mapping for generated traces);
* the golden fixtures' authoring conventions (``account_update`` /
  ``balance_check`` / ``long_technical_support`` exist only in fixtures).

Deliberately NOT in scope here: required-slot lists (``requires_slots``),
per-outcome effect matrices, or a per-scenario verdict policy. Those are the
Wave-2 scenario registry's job (PRD Sec.7's source-2 refinement); this module
is only what MISROUTED / PARTIALLY_RESOLVED emission needs.

A scenario_id absent from the registry carries no claim either way: verdicts
for unknown scenarios keep the pre-registry behavior exactly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioSpec:
    """What the scenario's caller asked for, minimally expressed.

    ``requires_mutation`` is the tool_name the intent's terminal required
    mutation must carry -- ``None`` for a lookup/informational intent that
    requires NO mutation at all."""
    requires_mutation: str | None


SCENARIO_REGISTRY: dict[str, ScenarioSpec] = {
    # Mutation intents (corpus SCENARIOS + fixture 17's authoring).
    "refund": ScenarioSpec(requires_mutation="process_refund"),
    "billing_dispute": ScenarioSpec(requires_mutation="adjust_billing"),
    "cancel_subscription": ScenarioSpec(requires_mutation="cancel_subscription"),
    "appointment_reschedule": ScenarioSpec(requires_mutation="reschedule_appointment"),
    # Fixture-only mutation intent (fixtures 05/10; not a corpus scenario).
    "account_update": ScenarioSpec(requires_mutation="update_address"),
    # Lookup/informational intents: a mutation would already be a misroute.
    "order_status": ScenarioSpec(requires_mutation=None),
    "tech_support": ScenarioSpec(requires_mutation=None),
    "balance_check": ScenarioSpec(requires_mutation=None),
    "long_technical_support": ScenarioSpec(requires_mutation=None),
}


def lookup(scenario_id: str) -> ScenarioSpec | None:
    """The scenario's spec, or ``None`` when the scenario is not registered
    (no claim either way)."""
    return SCENARIO_REGISTRY.get(scenario_id)
