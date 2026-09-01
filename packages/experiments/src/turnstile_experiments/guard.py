"""Fail-loud guard for VariantSpec fields the replay engine cannot execute.

Every ``Finding`` is contractually required to carry a ``proposed_variant``
"the replay engine can execute" (turnstile_schema.contracts.Finding docstring).
Today only ``model_routing`` is actually applied on the replay path
(``turnstile_replay.replay`` passes the variant straight to the backend, and
``turnstile_experiments.OpenAIBackend`` / ``turnstile_replay.MockBackend`` read
ONLY ``variant.model_routing``). The other six VariantSpec fields --
context_strategy, prefix_caching, retrieval_policy, tts_chunking,
escalation_policy, tool_batching -- are "reserved" (see
``turnstile_replay.backend`` docstring): a variant that sets one of them
replays as an identity no-op, producing a zero-delta trial that LOOKS like a
measured result but proves nothing.

That silent-no-op is the failure mode the first paid smoke run exposed (five of
six matrix variants were burning tokens on identical calls). This guard makes
it loud: any attempt to RUN a variant with a field no backend reads raises
``NotImplementedError`` at experiment start, before a cent is spent.
"""
from __future__ import annotations

from turnstile_schema import VariantSpec

# The only VariantSpec field any replay backend actually applies today.
IMPLEMENTED_VARIANT_FIELDS: frozenset[str] = frozenset({"model_routing"})

# Every field VariantSpec declares (derived, so it can't drift from the schema).
ALL_VARIANT_FIELDS: frozenset[str] = frozenset(VariantSpec.model_fields)

# Fields that are declared but not executable on the replay path -- each maps to
# a detector remedy (D2/D3/D4/D6/D7/D9/D10) that stays Tier-2 until replay learns
# to apply it. Exposed for docs/manifest, not used as a gate directly.
RESERVED_VARIANT_FIELDS: frozenset[str] = ALL_VARIANT_FIELDS - IMPLEMENTED_VARIANT_FIELDS


def set_fields(variant: VariantSpec) -> set[str]:
    """The VariantSpec fields this variant actually sets (non-``None``)."""
    return {f for f in ALL_VARIANT_FIELDS if getattr(variant, f) is not None}


def applied_fields(variant: VariantSpec) -> set[str]:
    """The subset of set fields the replay engine will actually apply."""
    return set_fields(variant) & IMPLEMENTED_VARIANT_FIELDS


def unimplemented_fields(variant: VariantSpec) -> set[str]:
    """The subset of set fields no backend reads -- would replay as a no-op."""
    return set_fields(variant) - IMPLEMENTED_VARIANT_FIELDS


def assert_variant_executable(name: str, variant: VariantSpec) -> None:
    """Raise ``NotImplementedError`` if ``variant`` sets any field the replay
    engine cannot execute (which would replay as a silent zero-delta no-op).

    Also rejects a variant that sets NOTHING at all -- an all-``None`` spec
    replays the identity, another no-op dressed as a measurement."""
    missing = unimplemented_fields(variant)
    if missing:
        raise NotImplementedError(
            f"variant {name!r} sets replay-unsupported field(s) "
            f"{sorted(missing)}: the replay engine only applies "
            f"{sorted(IMPLEMENTED_VARIANT_FIELDS)} today, so these would replay "
            f"as a zero-delta no-op that proves nothing. Refusing to run it "
            f"(and, on --paid, to spend on it). Implement the field on the "
            f"replay path, or move it to RESERVED_VARIANTS."
        )
    if not set_fields(variant):
        raise NotImplementedError(
            f"variant {name!r} sets no fields at all -- an identity replay is a "
            f"no-op, not a measurement."
        )
