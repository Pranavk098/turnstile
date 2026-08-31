"""``recoverable_margin`` -- PRD Sec.4.3, CORRECTED per the 2026-08-31 errata
(the original formula divided a dollar total by a dollars-per-conversation
rate, which is dimensionally incoherent -- see turnstile-prd.md Sec.4.3):

    Recoverable Margin % = Sigma proven_savings / Sigma total_cost x 100

``proven_savings`` sums only variants that pass BOTH PRD Sec.8.3 gates:

  * ``outcome_preservation_rate >= 0.95``
  * ``CI_lower(savings) > 0`` -- i.e. the bootstrap 95% CI upper bound on
    ``delta_cost`` is < 0. (``savings = -delta_cost``, so
    ``CI_lower(savings) = -delta_cost_ci95[1]``; requiring that be > 0 is
    exactly requiring ``delta_cost_ci95[1] < 0``.)

Never returns a bare point estimate -- see the return-shape docstring below.
"""
from __future__ import annotations

from turnstile_schema import ExperimentResult

GATE_MIN_PRESERVATION_RATE = 0.95


def _passes_gate(result: ExperimentResult) -> bool:
    _ci_lower, ci_upper = result.delta_cost_ci95
    return result.outcome_preservation_rate >= GATE_MIN_PRESERVATION_RATE and ci_upper < 0.0


def recoverable_margin(
    matrix: dict[str, ExperimentResult],
    total_cost: float,
    annual_calls: int,
) -> dict:
    """PRD Sec.4.3 (errata-corrected) recoverable margin over ``matrix``
    (``run_matrix()``'s output) against ``total_cost`` (Sigma total_cost --
    e.g. ``sum(pt.conv_cost for pt in corpus)`` for the SAME corpus the
    matrix ran on).

    A gated variant's per-trial mean ``delta_cost`` (and its bootstrap CI) is
    scaled by that variant's own trial count (``ExperimentResult.n``) to a
    total-dollar point estimate/CI for THIS matrix run, then gated variants
    are summed across the matrix. This is a linear-scaling approximation,
    stated as an assumption -- trials are not independent across variants
    (same corpus, different policies), so a rigorous joint CI across variants
    is out of scope here.

    Returns (never a bare point estimate):

    * ``recoverable_margin_pct``      -- point estimate, percent
    * ``recoverable_margin_pct_ci95`` -- ``[lo, hi]``, percent
    * ``total_cost_usd``              -- the ``total_cost`` argument, echoed
    * ``proven_savings_usd``          -- point estimate, dollars
    * ``proven_savings_usd_ci95``     -- ``[lo, hi]``, dollars
    * ``annualized_usd``              -- ``proven_savings_usd`` scaled by
      ``annual_calls / n_reference`` (assumption below)
    * ``annual_calls``                -- the ``annual_calls`` argument, echoed
    * ``n_reference``                 -- corpus-trial count used for the
      annualization scaling (see assumption)
    * ``gated_variants``              -- names of variants whose savings
      entered ``proven_savings``
    * ``excluded_variants``           -- the rest, with why they were excluded

    **Annualization assumption** (stated explicitly, PRD Sec.4.3 errata): the
    per-call savings rate observed on this run
    (``proven_savings_usd / n_reference``) is assumed representative of the
    fleet and scaled linearly to ``annual_calls``. ``n_reference`` is the
    largest trial count (``ExperimentResult.n``) seen across ``matrix`` -- the
    least-excluded variant, closest to "every corpus trace considered."
    """
    proven_savings_usd = 0.0
    ci_lower_usd = 0.0
    ci_upper_usd = 0.0
    gated_variants: list[str] = []
    excluded_variants: list[dict] = []
    n_reference = 0

    for name, result in matrix.items():
        n_reference = max(n_reference, result.n)
        if _passes_gate(result):
            gated_variants.append(name)
            savings_mean = -result.delta_cost_mean * result.n
            dc_lo, dc_hi = result.delta_cost_ci95
            # delta_cost_ci95 = (lo, hi) on Δcost; savings = -Δcost, so the
            # savings CI is (-hi, -lo); scale by n for a total-$ CI.
            proven_savings_usd += savings_mean
            ci_lower_usd += -dc_hi * result.n
            ci_upper_usd += -dc_lo * result.n
        else:
            excluded_variants.append({
                "variant": name,
                "outcome_preservation_rate": result.outcome_preservation_rate,
                "delta_cost_ci95": list(result.delta_cost_ci95),
            })

    def _pct(usd: float) -> float:
        return (usd / total_cost * 100.0) if total_cost > 0 else 0.0

    annualized_usd = (
        proven_savings_usd * (annual_calls / n_reference) if n_reference > 0 else 0.0
    )

    return {
        "recoverable_margin_pct": _pct(proven_savings_usd),
        "recoverable_margin_pct_ci95": [_pct(ci_lower_usd), _pct(ci_upper_usd)],
        "total_cost_usd": total_cost,
        "proven_savings_usd": proven_savings_usd,
        "proven_savings_usd_ci95": [ci_lower_usd, ci_upper_usd],
        "annualized_usd": annualized_usd,
        "annual_calls": annual_calls,
        "n_reference": n_reference,
        "gated_variants": gated_variants,
        "excluded_variants": excluded_variants,
    }
