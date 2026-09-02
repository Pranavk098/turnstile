"""Deterministic trace transforms for the Section-A re-pricing remedies
(docs/superpowers/GLM-OVERNIGHT-BATCH.md, Section A).

Each remedy transforms the trace deterministically (fewer tokens / cheaper
rate / dropped spans); ``turnstile_experiments.repricing`` then re-prices the
transformed trace via ``turnstile_pricing.price_trace`` and reports
delta_cost = transformed - original -- the same rate-arbitrage shape
``model_routing`` uses on the replay path, but with no backend and no spend.

The registry is per VariantSpec FIELD: ``REPRICING_TRANSFORMS[field]`` maps to
``fn(trace, value) -> Trace`` where ``value`` is the field's VariantSpec value
(``True`` for a bool field, the policy string for e.g. ``context_strategy``).
A variant is re-pricing-executable iff EVERY field it sets has an entry here;
``repricing.run_repricing_matrix`` refuses anything else (fail loud, same
philosophy as ``guard``).

Honesty contract shared by every transform here: these transforms REDUCE or
re-rate work, so each saving is CONDITIONAL on the change preserving the
conversation's outcome -- unmeasurable on the synthetic corpus (H-1, no
preservation data). Every figure derived from a transform must carry
``repricing.CONDITIONAL_SAVINGS_LABEL`` ("deterministic conditional saving --
preservation unverified (Wave-2)") and must stay OUT of the gated
``proven_savings`` bucket (``margin.recoverable_margin(conditional=...)``
enforces the separate bucket).
"""
from __future__ import annotations

from collections.abc import Callable

from turnstile_schema import Trace, VariantSpec

# VariantSpec field -> transform(trace, field_value) -> transformed trace.
# Pure functions: same trace + value in, same transformed trace out; no IO,
# no RNG, no backend.
REPRICING_TRANSFORMS: dict[str, Callable[[Trace, object], Trace]] = {}


def _register(field: str):
    def deco(fn):
        REPRICING_TRANSFORMS[field] = fn
        return fn
    return deco


@_register("prefix_caching")
def _transform_prefix_caching(trace: Trace, _value: object) -> Trace:
    """Re-price each decision's shared prefix at the ``cache_read`` rate
    (D2's remedy; the rate already exists in pricing/rates.yaml).

    Model (stated, deterministic): with append-only context, request i-1's
    full token count is the shared system+history prefix of request i, so
    under prompt caching those tokens bill at ``rate.cache_read`` instead of
    ``rate.input``. Per ``llm.decide`` span, in document order:

        new_cache_read = max(old_cache_read, min(prev_input, input_tokens))

    * the FIRST decision of a conversation gets no cache hit -- the cache is
      established BY it (honest default; ``cache_write_tokens`` is left
      untouched, which is also cost-neutral: rates.yaml prices cache_write
      at 0.0 -- OpenAI does not bill cache writes separately);
    * ``min(...)`` caps the shared prefix when context SHRANK between
      requests (pruning) -- exact under the corpus's monotonic context
      growth, an upper bound on the true shared prefix otherwise;
    * ``max(...)`` never REDUCES an existing cache hit.

    The prefix is re-billed, not removed: ``input_tokens`` (the workload) is
    unchanged, so the per-span delta is pure rate arbitrage,
    ``-prefix/1e6 * (rate.input - rate.cache_read)``, always <= 0.

    CONDITIONAL saving: bills the prefix at the cache rate, which matches
    real spend only if the deployment actually enables prompt caching and
    the provider's cache-hit conditions hold; that the outcome is preserved
    is NOT verified here (H-1). Report under the conditional label, never
    as a measured/proven saving.
    """
    new_turns = []
    prev_input = 0
    any_changed = False
    for turn in trace.turns:
        new_llm = []
        turn_changed = False
        for span in turn.llm:
            cache_read = max(span.cache_read_tokens, min(prev_input, span.input_tokens))
            if cache_read != span.cache_read_tokens:
                span = span.model_copy(update={"cache_read_tokens": cache_read})
                turn_changed = True
            new_llm.append(span)
            prev_input = span.input_tokens
        any_changed = any_changed or turn_changed
        new_turns.append(turn.model_copy(update={"llm": new_llm}) if turn_changed else turn)
    if not any_changed:
        return trace
    return trace.model_copy(update={"turns": new_turns})


def apply_variant_transform(trace: Trace, variant: VariantSpec) -> Trace:
    """Apply the re-pricing transform of every field ``variant`` sets, in
    VariantSpec field order, returning the transformed trace (the input is
    never mutated).

    Raises ``NotImplementedError`` if the variant sets a field with no
    transform (nothing silently replays as a no-op) or no fields at all."""
    set_ = [f for f in VariantSpec.model_fields if getattr(variant, f) is not None]
    if not set_:
        raise NotImplementedError(
            "variant sets no fields at all -- an identity transform is a "
            "no-op, not a measurement."
        )
    missing = [f for f in set_ if f not in REPRICING_TRANSFORMS]
    if missing:
        raise NotImplementedError(
            f"no deterministic re-pricing transform for field(s) {missing}: "
            f"implement it in turnstile_experiments.transforms first "
            f"(fields with a transform: {sorted(REPRICING_TRANSFORMS)})."
        )
    for f in set_:
        trace = REPRICING_TRANSFORMS[f](trace, getattr(variant, f))
    return trace
