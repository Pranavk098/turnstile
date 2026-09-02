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
from turnstile_experiments.transforms import (
    UNPRICED_DELTAS,
    apply_variant_transform,
)

from _experiments_builders import context, llm, priced, tool, turn

RATES = load_rates("pricing/rates.yaml")
GPT5 = RATES.llm["openai/gpt-5"]
MINI = RATES.llm["openai/gpt-5-mini"]

PREFIX_CACHING = REPRICING_VARIANTS["prefix_caching_on"]
TOOL_BATCHING = REPRICING_VARIANTS["tool_batching_on"]
WINDOW_8 = REPRICING_VARIANTS["context_window_8"]


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
# A2: tool_batching -> D10 (the deduped calls' vendor cost, nothing more)      #
# --------------------------------------------------------------------------- #

def test_tool_batching_delta_is_the_deduped_calls_vendor_cost():
    # Cross-turn repeat (the corpus's and fixture 10's shape): turn-1 re-calls
    # what turn-0 already called. The first call stays billed; the deduped
    # (removed) call's vendor cost is the saving.
    pt = priced(
        turn(0, llm_spans=[llm("l0")],
             tools_spans=[tool("t0", name="update_address", args_hash="h1", cost_usd=0.01)]),
        turn(1, llm_spans=[llm("l1")],
             tools_spans=[tool("t1", name="update_address", args_hash="h1", cost_usd=0.02)]),
    )
    result = run_repricing_experiment([pt], TOOL_BATCHING, rates=RATES)
    assert result.delta_cost_mean == pytest.approx(-0.02)

    tr = apply_variant_transform(pt.trace, TOOL_BATCHING)
    assert len(tr.turns[0].tools) == 1
    assert len(tr.turns[1].tools) == 0
    # The rate-priced stages are untouched: the whole delta is the unpriced
    # vendor term (ToolCall.cost_usd is excluded from price_trace by design).
    original = price_trace(pt.trace, RATES)
    transformed = price_trace(tr, RATES)
    assert transformed.conv_cost == pytest.approx(original.conv_cost)
    assert "tool_batching" in UNPRICED_DELTAS


def test_tool_batching_collapses_within_turn_duplicates():
    pt = priced(
        turn(0, llm_spans=[llm("l0")],
             tools_spans=[tool("t0", name="x", args_hash="h", cost_usd=0.01),
                          tool("t1", name="x", args_hash="h", cost_usd=0.02)]),
    )
    tr = apply_variant_transform(pt.trace, TOOL_BATCHING)
    assert [t.span_id for t in tr.turns[0].tools] == ["t0"]
    result = run_repricing_experiment([pt], TOOL_BATCHING, rates=RATES)
    assert result.delta_cost_mean == pytest.approx(-0.02)


def test_tool_batching_keeps_distinct_calls():
    # Same tool, different args -> not duplicates. Same args, different tool
    # -> not duplicates (D10 keys on the (tool_name, args_hash) pair).
    pt = priced(
        turn(0, llm_spans=[llm("l0")],
             tools_spans=[tool("t0", name="x", args_hash="h1", cost_usd=0.01),
                          tool("t1", name="x", args_hash="h2", cost_usd=0.02),
                          tool("t2", name="y", args_hash="h1", cost_usd=0.03)]),
    )
    tr = apply_variant_transform(pt.trace, TOOL_BATCHING)
    assert len(tr.turns[0].tools) == 3
    result = run_repricing_experiment([pt], TOOL_BATCHING, rates=RATES)
    assert result.delta_cost_mean == 0.0


def test_tool_batching_is_exactly_zero_when_vendor_cost_unrecorded():
    # The synthetic corpus records no vendor cost (cost_usd defaults to 0.0,
    # the generator never sets it), so the deterministic delta is exactly 0:
    # the redundancy's cost on THIS corpus is turn-level -- Detector 10's
    # Tier-2 waste -- and this remedy must not claim it by stealth. If the
    # corpus ever starts recording vendor costs, this test fails loudly and
    # the remedy's labeling must be re-checked.
    corpus = [price_trace(t, RATES) for t in generate_corpus(10, 0)]
    result = run_repricing_matrix(
        corpus, {"tool_batching_on": TOOL_BATCHING}, rates=RATES)["tool_batching_on"]
    assert result.n == 10
    assert result.delta_cost_mean == 0.0
    assert result.delta_cost_ci95 == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# A3: context_strategy="window:N" -> D2/D4 (truncate to the last N turns)      #
# --------------------------------------------------------------------------- #

def _windowed_corpus_pt(n_turns=10, history_step=50):
    # Corpus-shaped: turn i's llm input = system(100) + history_i, with
    # history_i = history_step * (i+1) growing monotonic and unpruned; each
    # turn's ContextAssemble mirrors that decomposition.
    turns = []
    for i in range(n_turns):
        hist = history_step * (i + 1)
        turns.append(turn(
            i,
            llm_spans=[llm(f"l{i}", model="gpt-5", input_tokens=100 + hist,
                           output_tokens=10)],
        ))
        turns[-1] = turns[-1].model_copy(update={
            "context": context(f"c{i}", history_tokens=hist)})
    return priced(*turns)


def test_context_window_delta_hand_computed_from_rates():
    pt = _windowed_corpus_pt(n_turns=10, history_step=50)
    result = run_repricing_experiment([pt], WINDOW_8, rates=RATES)
    # window:8 keeps the last 8 turns of history: turns 0..7 are unchanged
    # (fewer than 8 turns behind them); turn 8 drops H_0 = 50 tokens, turn 9
    # drops H_1 = 100 tokens (each at gpt-5's input rate).
    expected = -((50 + 100) / 1e6) * GPT5.input
    assert result.delta_cost_mean == pytest.approx(expected)
    assert result.n == 1


def test_context_window_truncates_exactly_the_out_of_window_turns():
    tr = apply_variant_transform(_windowed_corpus_pt(n_turns=10, history_step=50).trace,
                                 WINDOW_8)
    for i in range(8):
        # < 8 turns of history behind turn i -> unchanged
        assert tr.turns[i].llm[0].input_tokens == 100 + 50 * (i + 1)
    assert tr.turns[8].llm[0].input_tokens == 100 + 450 - 50   # dropped H_0
    assert tr.turns[9].llm[0].input_tokens == 100 + 500 - 100  # dropped H_1
    # floors hold: system(+retrieved) always kept
    assert tr.turns[8].llm[0].input_tokens >= 100


def test_context_window_short_traces_are_unchanged():
    pt = _windowed_corpus_pt(n_turns=3)
    result = run_repricing_experiment([pt], WINDOW_8, rates=RATES)
    assert result.delta_cost_mean == 0.0


def test_context_window_clamps_cache_tokens_to_the_reduced_input():
    turns = []
    for i in range(10):
        hist = 50 * (i + 1)
        llm_span = llm(f"l{i}", model="gpt-5", input_tokens=100 + hist,
                       output_tokens=10, cache_read_tokens=100 + hist)  # fully cached
        t = turn(i, llm_spans=[llm_span]).model_copy(update={
            "context": context(f"c{i}", history_tokens=hist)})
        turns.append(t)
    pt = priced(*turns)
    tr = apply_variant_transform(pt.trace, WINDOW_8)
    # turn 8: input 550 - H_0 (50) -> reduced input 500; the full cache hit
    # (550) clamps to the reduced input.
    assert tr.turns[8].llm[0].input_tokens == 500
    assert tr.turns[8].llm[0].cache_read_tokens == 500
    # and the re-priced formula stays coherent (no negative full-rate term):
    result = run_repricing_experiment([pt], WINDOW_8, rates=RATES)
    assert result.delta_cost_mean == pytest.approx(
        -((50 + 100) / 1e6) * GPT5.cache_read)


def test_context_window_turn_without_context_span_truncates_with_zero_floor():
    turns = []
    for i in range(10):
        hist = 50 * (i + 1)
        t = turn(i, llm_spans=[llm(f"l{i}", model="gpt-5", input_tokens=100 + hist,
                                   output_tokens=10)])
        if i != 9:  # last turn carries no ContextAssemble
            t = t.model_copy(update={"context": context(f"c{i}", history_tokens=hist)})
        turns.append(t)
    pt = priced(*turns)
    result = run_repricing_experiment([pt], WINDOW_8, rates=RATES)
    # turns 0..7 unchanged (< N behind); turn 8 truncates via H_0 (floored at
    # system+retrieved=100); turn 9 has no context span of its own, so it
    # truncates via H_1 with a 0 floor (stated in the transform's docstring).
    expected = -((50 + 100) / 1e6) * GPT5.input
    assert result.delta_cost_mean == pytest.approx(expected)


def test_context_window_refuses_unknown_policies():
    pt = _windowed_corpus_pt(n_turns=3)
    for policy in ("summarize:2000", "window", "window:0", "window:abc"):
        with pytest.raises(NotImplementedError, match="context_strategy"):
            run_repricing_experiment(
                [pt], VariantSpec(context_strategy=policy), rates=RATES)


def test_context_window_over_corpus_deterministic_never_positive():
    corpus = [price_trace(t, RATES) for t in generate_corpus(10, 0)]
    first = run_repricing_matrix(corpus, {"context_window_8": WINDOW_8}, rates=RATES)
    second = run_repricing_matrix(corpus, {"context_window_8": WINDOW_8}, rates=RATES)
    assert first == second
    r = first["context_window_8"]
    assert r.n == 10
    assert r.delta_cost_mean <= 0.0


# --------------------------------------------------------------------------- #
# Fail-loud refusals                                                           #
# --------------------------------------------------------------------------- #

def test_refuses_variant_without_a_transform():
    pt = _two_turn_pt()
    with pytest.raises(NotImplementedError, match="retrieval_policy"):
        run_repricing_experiment(
            [pt], VariantSpec(retrieval_policy="threshold:0.8"), rates=RATES)
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
    with pytest.raises(NotImplementedError, match="retrieval_policy"):
        run_repricing_matrix(
            corpus,
            {"prefix_caching_on": PREFIX_CACHING, "bad": VariantSpec(retrieval_policy="x")},
            rates=RATES,
        )
