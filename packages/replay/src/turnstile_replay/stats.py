"""Statistics for the experiment layer (PRD Sec.5 / Sec.8.3).

The numbers a skeptical CTO will challenge:

  * ``wilson_interval`` -- Wilson score interval on the outcome-preservation
    rate. The only sound interval for a binomial proportion at small n.
  * ``bootstrap_ci`` -- deterministic percentile bootstrap 95% CI on a mean
    (``numpy.random.default_rng(seed)``; no global RNG, no non-seeded draw).
  * ``aggregate_experiment`` -- collapse replay ``Trial`` results into one
    ``ExperimentResult``. Precisely which trials feed which statistic is
    documented below.

All resampling/percentile math is numpy's default (linear) convention.
"""
from __future__ import annotations

import math

import numpy as np

from turnstile_schema import ExperimentResult, Trial

DEFAULT_BOOTSTRAP_SEED = 12345

# --------------------------------------------------------------------------- #
# Wilson score interval                                                        #
# --------------------------------------------------------------------------- #

def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. ``n == 0`` -> ``(0.0, 0.0)``.

    ``p = k/n``, ``denom = 1 + z^2/n``, ``center = (p + z^2/(2n)) / denom``,
    ``margin = (z/denom) * sqrt(p(1-p)/n + z^2/(4n^2))``, interval
    ``(center - margin, center + margin)`` clamped to ``[0, 1]``.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


# --------------------------------------------------------------------------- #
# Percentile bootstrap CI on the mean                                          #
# --------------------------------------------------------------------------- #

def bootstrap_ci(
    values: list[float],
    *,
    n_resamples: int = 10000,
    ci: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the MEAN of ``values``.

    Deterministic given ``seed`` (each call draws from a fresh
    ``numpy.random.default_rng(seed)`` -- no shared/global RNG). Resamples
    ``values`` with replacement ``n_resamples`` times, takes the mean of each
    resample, and returns the ``(1-ci)/2`` and ``(1+ci)/2`` percentiles of that
    bootstrap distribution (e.g. 2.5th/97.5th for ``ci=0.95``). Empty ->
    ``(0.0, 0.0)``.
    """
    if len(values) == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    means = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        means[i] = rng.choice(arr, size=arr.size, replace=True).mean()
    alpha = (1.0 - ci) / 2.0
    lo, hi = np.percentile(means, [alpha * 100.0, (1.0 - alpha) * 100.0])
    return (float(lo), float(hi))


# --------------------------------------------------------------------------- #
# Trial aggregation                                                            #
# --------------------------------------------------------------------------- #

def aggregate_experiment(trials: list[Trial]) -> ExperimentResult:
    """Aggregate replay trials into an ``ExperimentResult``.

    Which trials feed which statistic (the subset rules that make the numbers
    challenge-proof):

    * ``n`` -- count of trials with ``status != "excluded"`` (ok + divergent).
    * ``outcome_preservation_rate`` -- mean of ``outcome_preserved`` over the
      non-excluded trials where it is not None (divergent trials with a
      preserved flag would count; normally they carry None). The rate is stored
      alone; its Wilson interval is computed by callers from the same counts
      via ``wilson_interval(successes, n)``.
    * ``delta_cost_mean`` / ``delta_cost_ci95`` -- mean and ``bootstrap_ci``
      over the ``delta_cost`` values (non-None) of trials that are
      **non-excluded AND non-divergent**.
    * ``delta_latency_p50`` / ``delta_latency_p95`` -- 50th/95th percentiles of
      ``delta_latency_ms`` (non-None) over the same non-excluded,
      non-divergent subset.
    * ``divergent_exemplars`` -- ``trace_id`` of every trial with
      ``status == "divergent"``.

    Empty subsets yield ``0.0`` / ``(0.0, 0.0)`` so the result always
    constructs.
    """
    non_excluded = [t for t in trials if t.status != "excluded"]
    n = len(non_excluded)

    preserved = [t.outcome_preserved for t in non_excluded if t.outcome_preserved is not None]
    rate = float(np.mean(preserved)) if preserved else 0.0

    delta_trials = [t for t in non_excluded if t.status != "divergent"]
    delta_costs = [t.delta_cost for t in delta_trials if t.delta_cost is not None]
    delta_cost_mean = float(np.mean(delta_costs)) if delta_costs else 0.0
    delta_cost_ci95 = bootstrap_ci(delta_costs) if delta_costs else (0.0, 0.0)

    latencies = [t.delta_latency_ms for t in delta_trials if t.delta_latency_ms is not None]
    p50 = float(np.percentile(latencies, 50)) if latencies else 0.0
    p95 = float(np.percentile(latencies, 95)) if latencies else 0.0

    divergent_exemplars = [t.trace_id for t in trials if t.status == "divergent"]

    return ExperimentResult(
        n=n,
        outcome_preservation_rate=rate,
        delta_cost_mean=delta_cost_mean,
        delta_cost_ci95=delta_cost_ci95,
        delta_latency_p50=p50,
        delta_latency_p95=p95,
        divergent_exemplars=divergent_exemplars,
    )