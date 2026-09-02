"""Tests for the deterministic re-pricing path (Section A task 1:
prefix_caching -> D2, docs/superpowers/GLM-OVERNIGHT-BATCH.md).

The acceptance core: a test hand-computing the delta from rates.yaml on a
small fixture-shaped trace; the honesty contract (conditional bucket, never
proven_savings, preservation label verbatim); and the fail-loud refusals.
"""
from __future__ import annotations

import pytest
from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_schema import VariantSpec, load_rates

from turnstile_experiments import (
    CONDITIONAL_SAVINGS_LABEL,
    REPRICING_VARIANTS,
    run_repricing_experiment,
    run_repricing_matrix,
)
from turnstile_experiments.transforms import apply_variant_transform

from _experiments_builders import llm, priced, turn

RATES = load_rates("pricing/rates.yaml")
GPT5 = RATES.llm["openai/gpt-5"]
MINI = RATES.llm["openai/gpt-5-mini"]

PREFIX_CACHING = REPRICING_VARIANTS["prefix_caching_on"]


def _two_turn_pt():
    # Fixture-shaped: turn-0's request is the shared system+history prefix
    # that turn-1's request re-sends in full.
    return priced(
        turn(0, llm_spans=[llm("l0", model="gpt-5", input_tokens=500, output_tokens=15)]),
        turn(1, llm_spans=[llm("l1", model="gpt-5", input_tokens=800, output_tokens=15)]),
    )


# --------------------------------------------------------------------------- #
# Hand-computed delta from rates.yaml                                          #
# --------------------------------------------------------------------------- #

def test_prefix_caching_delta_hand_computed_from_rates():
    pt = _two_turn_pt()
    result = run_repricing_experiment([pt], PREFIX_CACHING, rates=RATES)
    # Turn-1 re-bills turn-0's 500-token request at cache_read instead of
    # input; everything else is unchanged.
    expected = -(500 / 1e6) * (GPT5.input - GPT5.cache_read)
    assert result.delta_cost_mean == pytest.approx(expected)
    assert result.delta_cost_ci95 == pytest.approx((expected, expected))  # single trace
    assert result.n == 1
    assert result.label == CONDITIONAL_SAVINGS_LABEL


def test_transform_moves_only_the_shared_prefix_to_cache_read():
    tr = apply_variant_transform(_two_turn_pt().trace, PREFIX_CACHING)
    s0, s1 = tr.turns[0].llm[0], tr.turns[1].llm[0]
    assert s0.cache_read_tokens == 0    # first request establishes the cache
    assert s1.cache_read_tokens == 500  # = turn-0's request size
    assert (s0.input_tokens, s1.input_tokens) == (500, 800)  # workload intact
    assert s1.cache_write_tokens == 0   # cache_write untouched (0.0 rate)


def test_delta_is_exact_rate_arbitrage_on_the_prefix_tokens():
    # The conv_cost delta must equal the per-span arbitrage exactly, i.e. the
    # non-llm stages and the non-prefix tokens contribute nothing.
    pt = _two_turn_pt()
    original = price_trace(pt.trace, RATES)
    transformed = price_trace(apply_variant_transform(pt.trace, PREFIX_CACHING), RATES)
    assert transformed.conv_cost - original.conv_cost == pytest.approx(
        -(500 / 1e6) * (GPT5.input - GPT5.cache_read))


def test_each_span_billed_at_its_own_models_rate():
    pt = priced(
        turn(0, llm_spans=[llm("l0", model="gpt-5", input_tokens=500, output_tokens=15)]),
        turn(1, llm_spans=[llm("l1", model="gpt-5-mini", input_tokens=1000, output_tokens=15)]),
    )
    result = run_repricing_experiment([pt], PREFIX_CACHING, rates=RATES)
    expected = -(500 / 1e6) * (MINI.input - MINI.cache_read)
    assert result.delta_cost_mean == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# Edge cases of the prefix model                                               #
# --------------------------------------------------------------------------- #

def test_first_decision_and_llm_less_trace_get_zero_delta():
    single = priced(turn(0, llm_spans=[llm("l0", model="gpt-5")]))
    no_llm = priced(turn(0))
    for pt in (single, no_llm):
        result = run_repricing_experiment([pt], PREFIX_CACHING, rates=RATES)
        assert result.delta_cost_mean == 0.0
        assert result.n == 1


def test_existing_cache_hits_are_never_reduced():
    pt = priced(
        turn(0, llm_spans=[llm("l0", model="gpt-5", input_tokens=500, output_tokens=15)]),
        turn(1, llm_spans=[llm("l1", model="gpt-5", input_tokens=800, output_tokens=15,
                             cache_read_tokens=600)]),
    )
    tr = apply_variant_transform(pt.trace, PREFIX_CACHING)
    assert tr.turns[1].llm[0].cache_read_tokens == 600  # max() keeps the hit
    result = run_repricing_experiment([pt], PREFIX_CACHING, rates=RATES)
    assert result.delta_cost_mean == 0.0


def test_context_shrink_caps_the_prefix_at_the_current_request():
    pt = priced(
        turn(0, llm_spans=[llm("l0", model="gpt-5", input_tokens=500, output_tokens=15)]),
        turn(1, llm_spans=[llm("l1", model="gpt-5", input_tokens=300, output_tokens=15)]),
    )
    tr = apply_variant_transform(pt.trace, PREFIX_CACHING)
    assert tr.turns[1].llm[0].cache_read_tokens == 300
    expected = -(300 / 1e6) * (GPT5.input - GPT5.cache_read)
    result = run_repricing_experiment([pt], PREFIX_CACHING, rates=RATES)
    assert result.delta_cost_mean == pytest.approx(expected)


def test_transform_is_pure_input_trace_unchanged():
    pt = _two_turn_pt()
    before = pt.trace.model_dump()
    apply_variant_transform(pt.trace, PREFIX_CACHING)
    assert pt.trace.model_dump() == before


# --------------------------------------------------------------------------- #
# Corpus-level behavior: deterministic, savings-only, honest n                 #
# --------------------------------------------------------------------------- #

def test_real_corpus_deltas_deterministic_and_never_positive():
    corpus = [price_trace(t, RATES) for t in generate_corpus(10, 0)]
    first = run_repricing_matrix(corpus, REPRICING_VARIANTS, rates=RATES)
    second = run_repricing_matrix(corpus, REPRICING_VARIANTS, rates=RATES)
    assert first == second  # deterministic (seeded bootstrap, pure transforms)
    r = first["prefix_caching_on"]
    assert r.n == 10  # every trace counts; traces with nothing to cache -> 0.0
    assert r.delta_cost_mean <= 0.0  # caching re-bills cheaper, never costs more


# --------------------------------------------------------------------------- #
# Fail-loud refusals                                                           #
# --------------------------------------------------------------------------- #

def test_refuses_variant_without_a_transform():
    pt = _two_turn_pt()
    with pytest.raises(NotImplementedError, match="context_strategy"):
        run_repricing_experiment([pt], VariantSpec(context_strategy="window:8"), rates=RATES)
    with pytest.raises(NotImplementedError, match="no fields"):
        run_repricing_experiment([pt], VariantSpec(), rates=RATES)
    # A backend knob cannot ride the re-pricing path either.
    with pytest.raises(NotImplementedError, match="model_routing"):
        run_repricing_experiment(
            [pt], VariantSpec(model_routing={"route": "gpt-5-nano"}), rates=RATES)
    with pytest.raises(NotImplementedError, match="model_routing"):
        run_repricing_experiment(
            [pt],
            VariantSpec(model_routing={"route": "gpt-5-nano"}, prefix_caching=True),
            rates=RATES,
        )


def test_matrix_validates_all_variants_before_running_any():
    corpus = [price_trace(t, RATES) for t in generate_corpus(3, 0)]
    with pytest.raises(NotImplementedError, match="context_strategy"):
        run_repricing_matrix(
            corpus,
            {"prefix_caching_on": PREFIX_CACHING, "bad": VariantSpec(context_strategy="x")},
            rates=RATES,
        )
