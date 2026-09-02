"""Deterministic re-pricing experiments (Section A of
docs/superpowers/GLM-OVERNIGHT-BATCH.md) -- the execution path for remedy
variants whose knobs the replay backend does not read.

For each priced trace: apply the variant's deterministic transform
(``transforms.apply_variant_transform``), re-price the transformed trace via
``turnstile_pricing.price_trace``, and take delta = transformed - original.
No backend, no network, no spend -- exact arithmetic on rates.yaml.

HONESTY (the load-bearing rule): unlike ``model_routing`` (same workload,
cheaper rate -- an unconditional arbitrage), these transforms reduce or
re-rate work, so every saving here is CONDITIONAL on the change preserving
the conversation's outcome, which is unmeasurable on the synthetic corpus
(H-1). Accordingly:

* ``RepricingResult`` carries NO outcome-preservation figure -- there is
  none to report, and fabricating one is exactly what the honesty rule
  forbids;
* every number from this module must be presented under
  ``CONDITIONAL_SAVINGS_LABEL``;
* ``margin.recoverable_margin(conditional=...)`` keeps these results in a
  SEPARATE bucket, never added to gated ``proven_savings`` / the margin %;
* the PRD Sec.8.3 gate (preservation >= 0.95 AND ci_upper(delta_cost) < 0)
  can never pass for a re-pricing-only variant, because no preservation
  rate exists -- that is the honest state until Wave-2 preservation data
  lands.

CI convention: the same deterministic percentile bootstrap as the gated
numbers (``turnstile_stats.bootstrap_ci``, seed 12345); delta_cost follows
the replay convention (negative = saving).
"""
from __future__ import annotations

from dataclasses import dataclass

from turnstile_schema import PricedTrace, RateTable, VariantSpec, load_rates
from turnstile_pricing import price_trace
from turnstile_stats import bootstrap_ci

from turnstile_experiments.transforms import REPRICING_TRANSFORMS, apply_variant_transform
from turnstile_experiments.guard import set_fields

RATES_PATH = "pricing/rates.yaml"

# The batch doc's exact honesty label for Section-A contributions. Every
# conditional number must carry it verbatim.
CONDITIONAL_SAVINGS_LABEL = (
    "deterministic conditional saving — preservation unverified (Wave-2)"
)


@dataclass(frozen=True)
class RepricingResult:
    """Aggregate deterministic re-pricing result for one variant over a
    corpus. ``delta_cost_*`` follow the replay convention (negative =
    saving). Deliberately NO outcome-preservation field -- see module
    docstring."""

    n: int
    delta_cost_mean: float
    delta_cost_ci95: tuple[float, float]
    label: str = CONDITIONAL_SAVINGS_LABEL


def assert_variant_supported(name: str, variant: VariantSpec) -> None:
    """Raise ``NotImplementedError`` unless EVERY field ``variant`` sets has
    a deterministic transform (and it sets at least one) -- the re-pricing
    path's fail-loud gate, mirroring ``guard``: nothing silently returns a
    zero-delta result that looks measured."""
    fields = set_fields(variant)
    if not fields:
        raise NotImplementedError(
            f"variant {name!r} sets no fields at all -- an identity "
            f"re-pricing is a no-op, not a measurement."
        )
    missing = fields - set(REPRICING_TRANSFORMS)
    if missing:
        raise NotImplementedError(
            f"variant {name!r} sets field(s) {sorted(missing)} with no "
            f"deterministic re-pricing transform (fields with one: "
            f"{sorted(REPRICING_TRANSFORMS)}). Implement the transform in "
            f"turnstile_experiments.transforms first."
        )


def reprice_trace_delta(
    pt: PricedTrace, variant: VariantSpec, rates: RateTable
) -> float:
    """Delta = re-priced(transformed trace) - original, for ONE trace."""
    transformed = apply_variant_transform(pt.trace, variant)
    return price_trace(transformed, rates).conv_cost - pt.conv_cost


def run_repricing_experiment(
    corpus: list[PricedTrace],
    variant: VariantSpec,
    rates: RateTable | None = None,
) -> RepricingResult:
    """Deterministic re-pricing of ``variant`` over ``corpus``: per-trace
    transform + re-price (no backend, no preservation claim), aggregated
    with the same mean + bootstrap CI convention as the gated numbers.
    Every trace counts toward ``n`` (deterministic arithmetic always
    applies; a trace with nothing to transform contributes 0.0, honestly)."""
    assert_variant_supported("variant", variant)
    rates = rates if rates is not None else load_rates(RATES_PATH)
    deltas = [reprice_trace_delta(pt, variant, rates) for pt in corpus]
    return RepricingResult(
        n=len(deltas),
        delta_cost_mean=sum(deltas) / len(deltas) if deltas else 0.0,
        delta_cost_ci95=bootstrap_ci(deltas),
    )


def run_repricing_matrix(
    corpus: list[PricedTrace],
    variants: dict[str, VariantSpec],
    rates: RateTable | None = None,
) -> dict[str, RepricingResult]:
    """Run the deterministic re-pricing experiment for every ``(name,
    variant)``. All variants are validated (``assert_variant_supported``)
    BEFORE any work, mirroring ``run_matrix``'s fail-before-running gate."""
    for name, variant in variants.items():
        assert_variant_supported(name, variant)
    return {
        name: run_repricing_experiment(corpus, variant, rates)
        for name, variant in variants.items()
    }
