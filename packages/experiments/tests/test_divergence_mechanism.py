"""The divergence-mechanism test at the EXPERIMENTS layer (audit 07 §3's
still-missing gap): a fake backend forking the PIVOT DECISION must mark
trials ``status="divergent"``, and those trials must be EXCLUDED from the
Δcost aggregates while still counting toward ``n`` and being listed as
divergent exemplars -- end-to-end through ``run_matrix`` (and the checkpointed
paid path), not just at the replay layer.

Wave-2 (kind-aware gate): the pivot is a bounded-vocab ``route`` decision, so
the fork is induced through the LABEL channel -- the fake backend returns a
different parsed label for the chosen pair of traces (a different-text/same-
label reply is NOT divergent anymore; that case is the paraphrase signal the
gate exists to measure). The ok/divergent split stays controlled and the
exclusion observable: the aggregate equals the OK-trials-only mean, which
differs from the all-trials mean because the divergent traces' would-be
deltas are deliberately much larger.
"""
from __future__ import annotations

import pytest
from turnstile_replay import reset_backend
from turnstile_replay.backend import ReplayedDecision
from turnstile_schema import VariantSpec, load_rates

from turnstile_experiments import (
    run_matrix,
    run_matrix_checkpointed_detailed,
)

from _experiments_builders import llm, priced, turn

RATES = load_rates("pricing/rates.yaml")
GPT5 = RATES.llm["openai/gpt-5"]
NANO = RATES.llm["openai/gpt-5-nano"]
VARIANT = VariantSpec(model_routing={"route": "gpt-5-nano"})

DIVERGENT_IDS = {"c2", "c3"}
# A different parsed label: the kind-aware gate reads this as a fork. ("other"
# is a valid route label in the corpus's own vocabulary, so this is a real
# decision difference, not an unparseable passthrough.)
DIVERGENT_LABEL = "other"


def _trial_delta_cost_usd(input_tokens: int, output_tokens: int = 15) -> float:
    """The rate-arbitrage delta of one fully-rerouted decision, hand-computed
    from rates.yaml: price(orig usage @ nano) - price(orig usage @ gpt-5)."""
    return (
        input_tokens / 1e6 * (NANO.input - GPT5.input)
        + output_tokens / 1e6 * (NANO.output - GPT5.output)
    )


def _corpus():
    # c0/c1 stay ok; c2/c3 get their pivots rewritten below (divergent). The
    # divergent traces carry 10x the input tokens so their would-be deltas
    # would visibly drag the aggregate if the exclusion ever broke.
    return [
        priced(turn(0, llm_spans=[llm("l0", input_tokens=500, output_tokens=15)]),
               conversation_id="c0"),
        priced(turn(0, llm_spans=[llm("l0", input_tokens=500, output_tokens=15)]),
               conversation_id="c1"),
        priced(turn(0, llm_spans=[llm("l0", input_tokens=5000, output_tokens=15)]),
               conversation_id="c2"),
        priced(turn(0, llm_spans=[llm("l0", input_tokens=5000, output_tokens=15)]),
               conversation_id="c3"),
    ]


def _split_backend(context, original_span, variant):
    if context.conversation_id in DIVERGENT_IDS:
        decision_chosen = DIVERGENT_LABEL  # parsed label differs -> the pivot forks
    else:
        decision_chosen = original_span.decision_chosen  # same label -> no divergence
    return ReplayedDecision(
        model="gpt-5-nano",
        output_text=original_span.output_text,
        decision_chosen=decision_chosen,
        input_tokens=original_span.input_tokens,
        output_tokens=original_span.output_tokens,
        latency_ms=original_span.latency_ms,
    )


def test_experiments_layer_aggregate_excludes_divergent_delta_costs():
    reset_backend()
    corpus = _corpus()
    result = run_matrix(corpus, {"model_routing_gpt5_nano": VARIANT}, backend=_split_backend)["model_routing_gpt5_nano"]

    # Divergent trials count toward n (PRD Sec.8.3's honest exclusion rate)
    # and are listed as exemplars.
    assert result.n == 4
    assert set(result.divergent_exemplars) == DIVERGENT_IDS

    # THE mechanism: delta aggregates see ONLY the ok trials. The two ok
    # traces each reroute 500 input + 15 output tokens gpt-5 -> nano; the
    # divergent traces' 10x would-be deltas are absent from the mean.
    ok_only = _trial_delta_cost_usd(500)
    assert ok_only < 0  # nano is cheaper: a saving
    assert result.delta_cost_mean == pytest.approx(ok_only)
    # Both ok trials have the SAME delta, so the bootstrap CI collapses to it.
    lo, hi = result.delta_cost_ci95
    assert lo == pytest.approx(ok_only) and hi == pytest.approx(ok_only)

    all_trials_mean = (2 * _trial_delta_cost_usd(500)
                       + 2 * _trial_delta_cost_usd(5000)) / 4
    assert all_trials_mean != pytest.approx(result.delta_cost_mean)

    # Divergent trials carry NO preservation flag, so they drop out of the
    # rate's numerator AND denominator (aggregate_experiment's documented
    # rule): the 1.0 is over the 2 ok trials only -- and it is a Mock-free
    # fake-backend artifact (identical text => identical label), not a
    # measured preservation claim.
    assert result.outcome_preservation_rate == pytest.approx(1.0)
    reset_backend()


def test_divergence_exclusion_survives_the_checkpointed_path(tmp_path):
    """The paid, resumable runner must aggregate identically -- a divergent
    trial can never leak its delta into a gated number via a different path."""
    reset_backend()
    corpus = _corpus()
    expected = run_matrix(corpus, {"model_routing_gpt5_nano": VARIANT},
                          backend=_split_backend)
    got, _real = run_matrix_checkpointed_detailed(
        corpus, {"model_routing_gpt5_nano": VARIANT},
        tmp_path / "ck.jsonl", backend=_split_backend)
    assert got["model_routing_gpt5_nano"].model_dump() == \
        expected["model_routing_gpt5_nano"].model_dump()
    assert got["model_routing_gpt5_nano"].delta_cost_mean == pytest.approx(
        _trial_delta_cost_usd(500))
    reset_backend()


def test_no_divergence_when_the_pivot_is_identical():
    # Control: an identity backend (same model, same text, same usage)
    # produces zero divergences and a zero-delta aggregate -- the mechanism
    # fires on the DECISION (parsed label), not on rerouting or on cost
    # changes.
    reset_backend()
    corpus = _corpus()

    def identity_backend(context, original_span, variant):
        return ReplayedDecision(
            model=original_span.gen_ai_request_model,
            output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
        )

    result = run_matrix(corpus, {"model_routing_gpt5_nano": VARIANT},
                        backend=identity_backend)["model_routing_gpt5_nano"]
    assert result.divergent_exemplars == []
    assert result.delta_cost_mean == 0.0
    assert result.delta_cost_ci95 == (0.0, 0.0)
    assert result.n == 4
    reset_backend()