"""Real per-intent calibration from the corpus (GAP-07, PRD Sec.4.3).

``fixtures/sample/baselines.json`` is 7 hand-authored per-intent rows the
fixture-driven build uses (packages/detectors' fixture tests, packages/
dashboard's sample data). ``compute_baselines()`` is the corpus-scale
replacement it was always meant to give way to: it groups a *priced* corpus
by ``Conversation.scenario_id`` ("intent") and computes p50/p75 turn counts
and mean per-turn cost as REAL percentiles/means over the corpus, not
hand-picked numbers.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from turnstile_schema import Baselines, IntentBaseline, PricedTrace


def compute_baselines(corpus: list[PricedTrace]) -> Baselines:
    """Per-intent baselines computed from ``corpus``, grouped by
    ``scenario_id``.

    * ``p50_turns`` / ``p75_turns`` -- 50th/75th percentile (numpy's default
      linear interpolation, same convention ``turnstile_stats`` uses) of turn
      counts (``len(trace.turns)``), one sample per conversation.
    * ``mean_cost_per_turn`` -- mean of every individual turn's cost
      (``PricedTrace.turn_costs``), pooled across every conversation sharing
      that ``scenario_id`` (i.e. the mean is over turns, not over
      conversations).

    Scenario ids with no traces in ``corpus`` simply do not appear in the
    result -- there is nothing to calibrate them from.
    """
    turn_counts: dict[str, list[int]] = defaultdict(list)
    turn_costs: dict[str, list[float]] = defaultdict(list)

    for pt in corpus:
        scenario_id = pt.trace.conversation.scenario_id
        turn_counts[scenario_id].append(len(pt.trace.turns))
        turn_costs[scenario_id].extend(pt.turn_costs)

    per_intent: dict[str, IntentBaseline] = {}
    for scenario_id, counts in turn_counts.items():
        costs = turn_costs[scenario_id]
        per_intent[scenario_id] = IntentBaseline(
            p50_turns=float(np.percentile(counts, 50)),
            p75_turns=float(np.percentile(counts, 75)),
            mean_cost_per_turn=float(np.mean(costs)) if costs else 0.0,
        )
    return Baselines(per_intent=per_intent)
