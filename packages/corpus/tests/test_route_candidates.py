"""Route-candidate enrichment (glm-corpus-enrich-route, TDD -- written FIRST, red).

The fork oracle returns None on 2-way `[scenario_id, "other"]` route candidates
(a fork can only be "other": registry-undecidable). The route branch must offer
all registered scenarios + "other" so a fork can land on a decidable target --
DETERMINISTICALLY (static list from distributions.SCENARIOS, no rng draw) with
decision_chosen unchanged.

THE GATE (load-bearing): the seeded corpus must be RNG-neutral -- per-trace
priced totals + route chosen labels byte-identical to the pre-change
fingerprints. If this test goes red, the generation RNG stream was perturbed:
STOP and flag, do NOT re-baseline (owner/Claude decision).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from turnstile_pricing import price_trace
from turnstile_schema import load_rates
from turnstile_schema.enums import DecisionKind
from turnstile_verdict.fork_oracle import Decision, preserved_under_divergence
from turnstile_verdict.registry import lookup
from turnstile_corpus import distributions as dist
from turnstile_corpus.generate import generate_corpus

from pathlib import Path

RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

EXPECTED_CANDIDATES = [s.scenario_id for s in dist.SCENARIOS] + ["other"]

# Pre-change fingerprints: sha256 over per-trace
# [conversation_id, route decision_chosen labels, round(conv_cost, 9)] for
# generate_corpus(250, seed) + price_trace. Any rng-stream perturbation moves
# these. Recorded 2026-09-08 on wave0-foundation @ 072ee1c (pre-enrichment).
FINGERPRINTS = {
    0: "ca65f8554cc2ff5ae462bcea0f2c42de590754b7ccc891bd90c5d212d3c55412",
    8: "9ba25ba31502490f693c5cc4c523fa226087c80b80f4b140e6dc0068339afb0e",
}


def _route_spans(trace):
    return [
        span for turn in trace.turns for span in turn.llm
        if span.decision_kind is DecisionKind.route
    ]


def _fingerprint(seed: int) -> str:
    rates = load_rates(RATES)
    rows = []
    for trace in generate_corpus(250, seed):
        priced = price_trace(trace, rates)
        rows.append([
            trace.conversation.conversation_id,
            [span.decision_chosen for span in _route_spans(trace)],
            round(priced.conv_cost, 9),
        ])
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Enrichment shape: exact static list, chosen untouched.                       #
# --------------------------------------------------------------------------- #

def test_route_candidates_are_all_registered_scenarios_plus_other():
    expected_others = [s for s in EXPECTED_CANDIDATES if s != "other"]
    assert len(expected_others) >= 3  # the trace's own + at least two others
    for trace in generate_corpus(40, 7):
        for span in _route_spans(trace):
            assert span.decision_candidates == EXPECTED_CANDIDATES
            assert span.decision_chosen == trace.conversation.scenario_id
            assert "other" in span.decision_candidates


def test_route_chosen_is_always_the_trace_scenario_id():
    for seed in (0, 8):
        for trace in generate_corpus(250, seed):
            for span in _route_spans(trace):
                assert span.decision_chosen == trace.conversation.scenario_id


# --------------------------------------------------------------------------- #
# THE GATE: RNG-neutral fingerprints (STOP-and-flag on red, never re-baseline) #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("seed, expected", sorted(FINGERPRINTS.items()))
def test_seeded_corpus_fingerprint_is_byte_identical(seed, expected):
    assert _fingerprint(seed) == expected, (
        f"seed {seed}: corpus drift -- the generation RNG stream moved "
        "(STOP and flag; do NOT re-baseline the headline)"
    )


# --------------------------------------------------------------------------- #
# The point: a generated fork target the oracle can decide.                    #
# --------------------------------------------------------------------------- #

def test_enriched_candidates_contain_a_decidable_fork_target():
    """From REAL generated data: some candidate besides the trace's own label
    (and "other") is registry-registered with a different requires_mutation,
    and the oracle decides that fork (False) instead of None."""
    seen = False
    for trace in generate_corpus(40, 7):
        intent = trace.conversation.scenario_id
        intent_spec = lookup(intent)
        assert intent_spec is not None
        for span in _route_spans(trace):
            for candidate in span.decision_candidates:
                if candidate in (intent, "other"):
                    continue
                cand_spec = lookup(candidate)
                if cand_spec is None:
                    continue
                if cand_spec.requires_mutation != intent_spec.requires_mutation:
                    verdict = preserved_under_divergence(
                        intent,
                        Decision(kind=DecisionKind.route, label=intent),
                        Decision(kind=DecisionKind.route, label=candidate),
                    )
                    assert verdict is False
                    seen = True
    assert seen, "expected at least one decidable fork target in the sample"
