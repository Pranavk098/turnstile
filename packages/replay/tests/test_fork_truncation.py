"""Item 1 + Item 2 at the replay layer (TDD, written red).

Item 1: divergent trials must self-document the fork (forked_label /
forked_text / finish_reason) via ReplayOutcome so the checkpointed paid path
can persist them without a sidecar. ReplayedDecision carries finish_reason
(OpenAI computes it today but only logs it; Mock leaves None).

Item 2: finish_reason == "length" is a clipped reply -- the trial is
truncated (excluded from every aggregate, never silently scored), taking
precedence over the divergence gate. Mock never truncates.
"""
from __future__ import annotations

import pytest

from turnstile_schema import VariantSpec
from turnstile_schema.enums import DecisionKind
from turnstile_replay import (
    MockBackend,
    ReplayedDecision,
    replay,
    replay_with_real_usage_cost,
    reset_backend,
    set_backend,
)

from _replay_builders import llm, priced, turn


@pytest.fixture(autouse=True)
def _isolated_backend():
    reset_backend()
    yield
    reset_backend()


def _span(**overrides):
    fields = dict(
        decision_kind=DecisionKind.route,
        decision_chosen="billing_dispute",
        output_text="Order status. Let me look into that for you.",
    )
    fields.update(overrides)
    return llm("l0", **fields)


# --------------------------------------------------------------------------- #
# ReplayedDecision.finish_reason defaults to None (backwards compat).          #
# --------------------------------------------------------------------------- #

def test_replayed_decision_finish_reason_defaults_to_none():
    d = ReplayedDecision(
        model="gpt-5", output_text="x", decision_chosen="x",
        input_tokens=1, output_tokens=1,
    )
    assert d.finish_reason is None


def test_mock_backend_leaves_finish_reason_none():
    span = _span()
    ctx_kwargs = dict(conversation_id="c1", scenario_id="s", turn_index=0, turns_before=())
    from turnstile_replay.backend import ReplayContext

    ctx = ReplayContext(**ctx_kwargs)
    d = MockBackend()(ctx, span, VariantSpec(model_routing={"route": "gpt-5-nano"}))
    assert d.finish_reason is None


# --------------------------------------------------------------------------- #
# Item 1: divergent outcome carries the fork.                                  #
# --------------------------------------------------------------------------- #

def test_divergent_outcome_carries_forked_label_text_and_finish_reason():
    span = _span()
    pt = priced(turn(0, llm_spans=[span]))

    def _fork(context, original_span, variant):
        return ReplayedDecision(
            model="gpt-5-nano",
            output_text="Sure, other department handling this.",
            decision_chosen="other",
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
            finish_reason="stop",
        )

    set_backend(_fork)
    outcome = replay_with_real_usage_cost(
        pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert outcome.trial.status == "divergent"
    assert outcome.forked_label == "other"
    assert outcome.forked_text == "Sure, other department handling this."
    assert outcome.finish_reason == "stop"
    assert outcome.truncated is False


def test_ok_outcome_is_not_truncated_and_carries_finish_reason():
    span = _span()
    pt = priced(turn(0, llm_spans=[span]))

    def _ok(context, original_span, variant):
        return ReplayedDecision(
            model="gpt-5-nano",
            output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
            finish_reason="stop",
        )

    set_backend(_ok)
    outcome = replay_with_real_usage_cost(
        pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert outcome.trial.status == "ok"
    assert outcome.truncated is False
    assert outcome.finish_reason == "stop"
    assert outcome.forked_label is None


# --------------------------------------------------------------------------- #
# Item 2: finish_reason == "length" -> truncated (excluded, never scored).     #
# --------------------------------------------------------------------------- #

def test_length_finish_reason_marks_trial_truncated_excluded():
    span = _span()
    pt = priced(turn(0, llm_spans=[span]))

    def _clipped(context, original_span, variant):
        return ReplayedDecision(
            model="gpt-5-nano",
            output_text="Partial reply that was cut",
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=256,
            reasoning_tokens=240,
            latency_ms=original_span.latency_ms,
            finish_reason="length",
        )

    set_backend(_clipped)
    outcome = replay_with_real_usage_cost(
        pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    # Truncated trials are excluded from every aggregate (out of n entirely),
    # never folded as ok/divergent.
    assert outcome.trial.status == "excluded"
    assert outcome.truncated is True
    assert outcome.finish_reason == "length"
    assert outcome.trial.delta_cost is None
    assert outcome.trial.outcome_preserved is None
    assert outcome.delta_cost_real_usage is None
    # Reasoning/content split rides along for the exemplar block.
    assert outcome.truncated_reasoning_tokens == 240
    assert outcome.truncated_output_tokens == 256


def test_truncation_takes_precedence_over_divergence():
    """A clipped reply with a different label is still truncated (excluded),
    never divergent -- a clipped decision is untrustworthy, not a fork."""
    span = _span()
    pt = priced(turn(0, llm_spans=[span]))

    def _clipped_fork(context, original_span, variant):
        return ReplayedDecision(
            model="gpt-5-nano",
            output_text="Clipped but different",
            decision_chosen="other",
            input_tokens=original_span.input_tokens,
            output_tokens=256,
            latency_ms=original_span.latency_ms,
            finish_reason="length",
        )

    set_backend(_clipped_fork)
    outcome = replay_with_real_usage_cost(
        pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert outcome.trial.status == "excluded"
    assert outcome.truncated is True
    assert outcome.forked_label is None


def test_stop_finish_reason_does_not_truncate():
    span = _span()
    pt = priced(turn(0, llm_spans=[span]))

    def _ok_stop(context, original_span, variant):
        return ReplayedDecision(
            model="gpt-5-nano",
            output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
            finish_reason="stop",
        )

    set_backend(_ok_stop)
    trial = replay(pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"


def test_any_truncated_span_in_multi_span_trace_truncates_the_trial():
    """Any clipped completion poisons the trial, not just the pivot."""
    s0 = llm("l0", decision_kind=DecisionKind.route, decision_chosen="billing_dispute",
             output_text="pivot text")
    s1 = llm("l1", decision_kind=DecisionKind.compose, decision_chosen="inform",
             output_text="second text")
    pt = priced(turn(0, llm_spans=[s0, s1]))

    def _second_clipped(context, original_span, variant):
        if original_span.span_id == "l1":
            return ReplayedDecision(
                model="gpt-5-nano", output_text="clipped tail",
                decision_chosen=original_span.decision_chosen,
                input_tokens=original_span.input_tokens,
                output_tokens=256, latency_ms=original_span.latency_ms,
                finish_reason="length",
            )
        return ReplayedDecision(
            model="gpt-5-nano", output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
            finish_reason="stop",
        )

    set_backend(_second_clipped)
    outcome = replay_with_real_usage_cost(
        pt, VariantSpec(model_routing={"route": "gpt-5-nano"}), from_turn=0)
    assert outcome.truncated is True
    assert outcome.trial.status == "excluded"
