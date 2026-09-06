"""``estimate_cost`` -- dollar estimate for running ``variants`` against
``corpus`` through a REAL backend, used to size a paid run before it happens
(and to print the figure a ``--paid`` CLI invocation must show before it can
proceed, docs/CORPUS.md's "gated owner approval").

For each variant, estimates the set of ``llm.decide`` decisions a real
backend would re-run -- the same "earliest applicable turn" rule
``turnstile_replay.replay._earliest_applicable_turn`` uses (imported directly,
single source of truth, same as ``turnstile_experiments.checkpoint_runner``)
-- and prices each
re-run decision's INPUT + OUTPUT tokens (no ``cache_read``/``cache_write``
credit: a live re-run is a fresh API call, not guaranteed to hit OpenAI's own
prompt cache, so this is a deliberately conservative/upper-bound estimate) at
the model the variant would route it to (``variant.model_routing``, falling
back to the span's original model when the variant doesn't touch this
decision -- matching ``turnstile_replay.backend``'s documented "or the
original span's model" fallback).
"""
from __future__ import annotations

from turnstile_schema import PricedTrace, RateTable, VariantSpec, load_rates
from turnstile_schema.spans import LlmDecide
from turnstile_replay.replay import _earliest_applicable_turn

RATES_PATH = "pricing/rates.yaml"


def _targets(trace: PricedTrace, variant: VariantSpec) -> list[LlmDecide]:
    from_turn = _earliest_applicable_turn(trace, variant)
    return [
        span
        for turn in trace.trace.turns
        if turn.turn_index >= from_turn
        for span in turn.llm
    ]


def _decision_cost_usd(span: LlmDecide, variant: VariantSpec, rates: RateTable) -> float:
    model = span.gen_ai_request_model
    if variant.model_routing:
        model = variant.model_routing.get(span.decision_kind.value, model)
    rate = rates.llm[f"{span.gen_ai_system}/{model}"]
    return span.input_tokens / 1e6 * rate.input + span.output_tokens / 1e6 * rate.output


def estimate_cost(
    corpus: list[PricedTrace],
    variants: dict[str, VariantSpec],
    rates: RateTable | None = None,
) -> dict:
    """Estimate + PRINT the $ cost of running ``variants`` against ``corpus``
    through a real backend. Returns
    ``{"per_variant": {name: {"num_decisions", "estimated_usd"}},
    "total_estimated_usd"}``."""
    rates = rates if rates is not None else load_rates(RATES_PATH)

    per_variant: dict[str, dict] = {}
    total_usd = 0.0
    print(f"Estimated cost for the {len(variants)}-variant x {len(corpus)}-trace real-backend matrix:")
    for name, variant in variants.items():
        n_decisions = 0
        usd = 0.0
        for trace in corpus:
            targets = _targets(trace, variant)
            n_decisions += len(targets)
            usd += sum(_decision_cost_usd(s, variant, rates) for s in targets)
        per_variant[name] = {"num_decisions": n_decisions, "estimated_usd": usd}
        total_usd += usd
        print(f"  {name:28s} {n_decisions:6d} decisions  ${usd:9.4f}")
    print(f"  {'TOTAL':28s} {'':6s}             ${total_usd:9.4f}")

    return {"per_variant": per_variant, "total_estimated_usd": total_usd}
