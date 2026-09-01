"""Tests for the counterfactual replay engine (packages/replay, PRD Sec.5/Sec.8).

Layers:
  * Acceptance -- the four criteria in the task brief, verbatim.
  * Fixture layer -- replay()/experiment() run cleanly over the 23 golden
    fixtures (contract-test style, mirrors the other packages' fixture layer).
  * Unit layer -- MockBackend's three rules, excluded/identity/tool-cache
    edge cases, and the injectable-backend contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from turnstile_schema import ExperimentResult, Trial, VariantSpec, load_rates, load_trace
from turnstile_schema.enums import DecisionKind, EndReason, ToolKind
from turnstile_pricing import price_trace
from turnstile_replay import (
    DIVERGENCE_SIMILARITY_THRESHOLD,
    MOCK_SAFE_REROUTE_MODELS,
    MockBackend,
    ReplayContext,
    ReplayedDecision,
    experiment,
    get_backend,
    replay,
    replay_with_real_usage_cost,
    reset_backend,
    set_backend,
)

from _replay_builders import llm, priced, tool, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

# Fixtures whose only llm.decide span with decision_kind="route" makes them
# reachable by the model_routing={"route": ...} variant used throughout.
ROUTE_FIXTURES = (
    "00_baseline_clean", "01_over_model", "03_redundant_retrieval",
    "11_multi_waste_a", "13_multi_waste_c", "20_unknown_mutation",
)


def _all_fixture_ids() -> list[str]:
    fixtures = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
    return [f["id"] for f in fixtures]


def _priced_fixture(fid: str):
    return price_trace(load_trace((GOLDEN / fid).with_suffix(".json")), load_rates(RATES))


@pytest.fixture(autouse=True)
def _clean_backend():
    """MockBackend is the default; guard every test against a leaked
    set_backend() from a prior test."""
    reset_backend()
    yield
    reset_backend()


# --------------------------------------------------------------------------- #
# Acceptance criteria (task brief, verbatim)                                   #
# --------------------------------------------------------------------------- #

def test_acceptance_1_over_model_cheaper_path_same_outcome():
    pt = _priced_fixture("01_over_model")
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"
    assert trial.delta_cost < 0
    assert trial.outcome_preserved is True
    # actual (gpt-5): 500/1e6*1.25 + 15/1e6*10.00 ; nano: 500/1e6*0.05 + 15/1e6*0.40
    expected_delta = (500 / 1e6 * 0.05 + 15 / 1e6 * 0.40) - (500 / 1e6 * 1.25 + 15 / 1e6 * 10.00)
    assert trial.delta_cost == pytest.approx(expected_delta)


def test_acceptance_2_divergent_reroute_marks_trial_divergent():
    pt = _priced_fixture("01_over_model")
    variant = VariantSpec(model_routing={"route": "gpt-9-untested-model"})
    trial = replay(pt, variant, from_turn=0)
    assert trial.status == "divergent"
    assert trial.delta_cost is None
    assert trial.delta_latency_ms is None
    assert trial.outcome_preserved is None


def test_acceptance_3_experiment_aggregates_golden_corpus():
    traces = [_priced_fixture(fid) for fid in _all_fixture_ids()]
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})
    result = experiment(traces, variant)

    assert isinstance(result, ExperimentResult)
    # n excludes the "excluded" trials (fixtures with no "route" decision).
    assert result.n == len(ROUTE_FIXTURES)
    # Safe reroute never diverges -> no exemplars, full preservation.
    assert result.divergent_exemplars == []
    assert result.outcome_preservation_rate == pytest.approx(1.0)
    # gpt-5-nano is the cheapest tier in rates.yaml -> savings, never a loss.
    assert result.delta_cost_mean < 0
    lo, hi = result.delta_cost_ci95
    assert lo <= result.delta_cost_mean <= hi


def test_acceptance_4_backend_is_genuinely_injectable():
    calls = []

    def custom_backend(context: ReplayContext, original_span, variant: VariantSpec) -> ReplayedDecision:
        calls.append((context.turn_index, original_span.span_id))
        return ReplayedDecision(
            model="gpt-5-mini", output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=10, output_tokens=5, latency_ms=original_span.latency_ms,
        )

    set_backend(custom_backend)
    assert get_backend() is custom_backend

    pt = _priced_fixture("01_over_model")
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)

    # custom_backend ignores the variant's routing target entirely and always
    # reroutes to gpt-5-mini with fixed token counts -- proves replay() used
    # the injected callable, not MockBackend.
    assert calls == [(0, "l0")]
    assert trial.status == "ok"
    # CR-B rate arbitrage: ORIGINAL workload (500 in / 15 out) priced at the
    # replayed model (gpt-5-mini) vs the original model (gpt-5).
    expected_delta = (500 / 1e6 * 0.25 + 15 / 1e6 * 2.00) - (500 / 1e6 * 1.25 + 15 / 1e6 * 10.00)
    assert trial.delta_cost == pytest.approx(expected_delta)


# --------------------------------------------------------------------------- #
# CR-B acceptance -- delta_cost is deterministic rate arbitrage on the         #
# ORIGINAL workload, decoupled from the render.                                #
# --------------------------------------------------------------------------- #

def _realistic_reroute_backend(context, original_span, variant):
    """Stands in for a real backend on a genuine reroute: gpt-5 -> gpt-5-nano
    with REAL-scale usage (~85-token rendered prompt, ~200-token reply) --
    deliberately NOT the corpus's synthetic 500/15."""
    return ReplayedDecision(
        model="gpt-5-nano", output_text=original_span.output_text,
        decision_chosen=original_span.decision_chosen,
        input_tokens=85, output_tokens=200, latency_ms=original_span.latency_ms,
    )


def test_acceptance_reroute_delta_is_deterministic_rate_arbitrage():
    """A genuine reroute (gpt-5 -> gpt-5-nano) must yield the delta
    hand-computed from rates.yaml on the ORIGINAL workload -- invariant to
    the real usage the backend returned (the render-scale mismatch that made
    re-priced deltas spuriously negative)."""
    set_backend(_realistic_reroute_backend)
    pt = _priced_fixture("01_over_model")
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"
    # orig 500 in / 15 out: gpt-5 1.25/10.00 per Mtok vs nano 0.05/0.40.
    expected = (500 / 1e6 * 0.05 + 15 / 1e6 * 0.40) - (500 / 1e6 * 1.25 + 15 / 1e6 * 10.00)
    assert trial.delta_cost == pytest.approx(expected)


def test_acceptance_identity_replay_yields_zero_delta_cost():
    """A mocked 'real' backend that returns the ORIGINAL span's model AND
    usage must give delta_cost == 0 exactly: any variant-invariant bias in
    the cost figure (the CR-B bug) would show up as a systematic nonzero."""
    def identity_real_backend(context, original_span, variant):
        return ReplayedDecision(
            model=original_span.gen_ai_request_model,
            output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
        )

    set_backend(identity_real_backend)
    pt = _priced_fixture("01_over_model")
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"
    assert trial.delta_cost == pytest.approx(0.0, abs=1e-12)


def test_real_usage_companion_figure_priced_on_replayed_usage():
    """delta_cost_real_usage: SAME rate-arbitrage formula, but on the REAL
    replayed usage -- hand-computable from rates.yaml, and explicitly NOT
    equal to the gated figure when render scale differs."""
    set_backend(_realistic_reroute_backend)
    pt = _priced_fixture("01_over_model")
    outcome = replay_with_real_usage_cost(
        pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    trial = outcome.trial
    assert trial.status == "ok"
    # Real usage 85 in / 200 out, priced nano vs gpt-5.
    expected_real = (85 / 1e6 * 0.05 + 200 / 1e6 * 0.40) - (85 / 1e6 * 1.25 + 200 / 1e6 * 10.00)
    assert outcome.delta_cost_real_usage == pytest.approx(expected_real)
    # ...and it is a different figure from the gated, orig-workload delta.
    assert outcome.delta_cost_real_usage != pytest.approx(trial.delta_cost)


def test_real_usage_companion_is_none_for_excluded_and_divergent():
    pt_divergent = _priced_fixture("01_over_model")
    outcome = replay_with_real_usage_cost(
        pt_divergent, VariantSpec(model_routing={"route": "gpt-9-untested-model"}), from_turn=0)
    assert outcome.trial.status == "divergent"
    assert outcome.delta_cost_real_usage is None

    pt_empty = priced(turn(0, llm_spans=[llm("l0")]))
    outcome = replay_with_real_usage_cost(pt_empty, VariantSpec(), from_turn=5)
    assert outcome.trial.status == "excluded"
    assert outcome.delta_cost_real_usage is None


# --------------------------------------------------------------------------- #
# Fixture layer                                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fid", _all_fixture_ids())
def test_replay_runs_cleanly_over_every_golden_fixture(fid):
    pt = _priced_fixture(fid)
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert isinstance(trial, Trial)
    assert trial.status in ("ok", "divergent", "excluded")
    assert trial.trace_id == pt.trace.conversation.conversation_id


def test_experiment_over_full_golden_corpus_returns_valid_result():
    traces = [_priced_fixture(fid) for fid in _all_fixture_ids()]
    result = experiment(traces, VariantSpec(model_routing={"route": "gpt-5-nano"}))
    assert 0 <= result.n <= len(traces)
    assert 0.0 <= result.outcome_preservation_rate <= 1.0


# --------------------------------------------------------------------------- #
# Unit layer -- MockBackend                                                    #
# --------------------------------------------------------------------------- #

def test_mock_backend_identity_when_no_matching_model_routing_entry():
    span = llm("l0", decision_kind=DecisionKind.compose, output_text="hello there")
    ctx = ReplayContext(conversation_id="c1", scenario_id="s1", turn_index=0, turns_before=())
    decision = MockBackend()(ctx, span, VariantSpec(model_routing={"route": "gpt-5-nano"}))
    assert decision.model == span.gen_ai_request_model
    assert decision.output_text == span.output_text
    assert decision.decision_chosen == span.decision_chosen


def test_mock_backend_no_model_routing_at_all_is_identity():
    span = llm("l0", decision_kind=DecisionKind.route)
    ctx = ReplayContext(conversation_id="c1", scenario_id="s1", turn_index=0, turns_before=())
    decision = MockBackend()(ctx, span, VariantSpec())
    assert decision.model == span.gen_ai_request_model
    assert decision.output_text == span.output_text


def test_mock_backend_safe_reroute_preserves_output_text_and_decision():
    span = llm("l0", decision_kind=DecisionKind.route, output_text="Order status.",
               decision_chosen="order_status")
    ctx = ReplayContext(conversation_id="c1", scenario_id="s1", turn_index=0, turns_before=())
    for target in MOCK_SAFE_REROUTE_MODELS:
        decision = MockBackend()(ctx, span, VariantSpec(model_routing={"route": target}))
        assert decision.model == target
        assert decision.output_text == span.output_text
        assert decision.decision_chosen == span.decision_chosen


def test_mock_backend_unsafe_reroute_produces_low_similarity_output():
    import difflib
    span = llm("l0", decision_kind=DecisionKind.route, output_text="Order status.")
    ctx = ReplayContext(conversation_id="c1", scenario_id="s1", turn_index=0, turns_before=())
    decision = MockBackend()(ctx, span, VariantSpec(model_routing={"route": "some-other-model"}))
    ratio = difflib.SequenceMatcher(None, span.output_text, decision.output_text).ratio()
    assert ratio < DIVERGENCE_SIMILARITY_THRESHOLD


# --------------------------------------------------------------------------- #
# Unit layer -- replay() edge cases                                            #
# --------------------------------------------------------------------------- #

def test_from_turn_past_end_of_trace_is_excluded():
    pt = priced(turn(0, llm_spans=[llm("l0")]))
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=5)
    assert trial.status == "excluded"
    assert trial.delta_cost is None
    assert trial.delta_latency_ms is None
    assert trial.outcome_preserved is None


def test_variant_with_no_matching_decision_kind_is_identity_zero_delta():
    pt = priced(turn(0, llm_spans=[llm("l0", decision_kind=DecisionKind.route,
                                        input_tokens=500, output_tokens=15)]))
    trial = replay(pt, VariantSpec(model_routing={"compose": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"
    assert trial.delta_cost == pytest.approx(0.0)
    assert trial.delta_latency_ms == pytest.approx(0.0)
    assert trial.outcome_preserved is True


def test_tool_spans_are_pinned_through_the_args_hash_cache():
    original_tool = tool("t0", name="lookup_order", args_hash="sha256:fixed",
                          kind=ToolKind.lookup, effect="none")
    pt = priced(turn(0, llm_spans=[llm("l0", decision_kind=DecisionKind.route)],
                      tools=[original_tool]))
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"
    # Cost is unaffected by the (pinned, unpriced) tool span either way; this
    # test exists to exercise _tool_cache's args_hash lookup path without
    # crashing and without altering pricing/verdict outcomes.
    assert trial.outcome_preserved is True


def test_custom_backend_can_flip_the_outcome_and_replay_detects_it():
    """A verdict-changing replay: the tool's mutation effect stays rejected
    (pinned), but the backend rewrites the agent's final utterance to assert
    completion -- FALSE_RESOLVE where the original was UNRESOLVED. Confirms
    outcome_preserved is computed from the REPLAYED verdict, not assumed."""
    original_text = "I am working on your request now."
    replayed_text = "I am done processing your request now."  # similarity ~0.79, not divergent

    def backend(context, original_span, variant):
        return ReplayedDecision(
            model=original_span.gen_ai_request_model, output_text=replayed_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens, output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
        )

    set_backend(backend)
    pt = priced(turn(
        0, llm_spans=[llm("l0", decision_kind=DecisionKind.compose, output_text=original_text)],
        tools=[tool("t0", kind=ToolKind.mutation, effect="rejected")],
    ))
    trial = replay(pt, VariantSpec(), from_turn=0)
    assert trial.status == "ok"
    assert trial.outcome_preserved is False


def test_tool_cache_keys_by_args_hash_across_the_whole_trace():
    from turnstile_replay.replay import _tool_cache

    t1 = tool("t0", args_hash="sha256:aaa", kind=ToolKind.lookup, effect="none")
    t2 = tool("t1", args_hash="sha256:bbb", kind=ToolKind.mutation, effect="committed")
    tr = priced(
        turn(0, llm_spans=[llm("l0")], tools=[t1]),
        turn(1, llm_spans=[llm("l1")], tools=[t2]),
    ).trace
    cache = _tool_cache(tr)
    assert cache["sha256:aaa"].span_id == "t0"
    assert cache["sha256:bbb"].span_id == "t1"
    assert len(cache) == 2


def test_experiment_lists_divergent_exemplars_and_counts_them_in_n():
    ok_trace = priced(turn(0, llm_spans=[llm("l0", decision_kind=DecisionKind.route)]),
                       conversation_id="ok-trace")
    diverge_trace = priced(turn(0, llm_spans=[llm("l1", decision_kind=DecisionKind.route)]),
                            conversation_id="diverge-trace")

    def backend(context, original_span, variant):
        if context.conversation_id == "diverge-trace":
            return ReplayedDecision(
                model="gpt-5-nano", output_text="completely different reply",
                decision_chosen="other", input_tokens=original_span.input_tokens,
                output_tokens=original_span.output_tokens, latency_ms=original_span.latency_ms,
            )
        return ReplayedDecision(
            model="gpt-5-nano", output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens, output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
        )

    set_backend(backend)
    result = experiment([ok_trace, diverge_trace], VariantSpec(model_routing={"route": "gpt-5-nano"}))
    assert result.n == 2
    assert result.divergent_exemplars == ["diverge-trace"]
