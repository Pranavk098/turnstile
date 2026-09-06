"""Wave-2 Item 2: the KIND-AWARE decision divergence gate (TDD).

The difflib-on-full-text gate died on real model replies (paid evidence
2026-09-06: 217/217 divergent at ~0.04 lexical similarity despite sensible
decisions). The new gate, per the finalized ruling:

* bounded-vocab kinds (route / tool_select / escalate_check / compose):
  divergent iff the replayed decision's parsed label differs from the
  original span's recorded (parsed) label; an unparseable replayed reply
  (raw passthrough) is divergent -- never folded as preserved;
* slot_fill: UNCHANGED content/_similarity path (single-label kind whose
  verdict rides on utterance content) -- the W3-C authored probes in
  packages/experiments/tests/test_preservation.py must classify EXACTLY as
  before; a label gate marking the break case preserved is the forbidden
  regression these guards pin.

These tests were written FIRST and verified red against the old text gate
(the bounded-kind expectations fail under it); the implementation makes them
green without moving the slot_fill guards.
"""
from __future__ import annotations

import pytest

from turnstile_schema import VariantSpec
from turnstile_schema.enums import DecisionKind
from turnstile_replay import (
    ReplayedDecision,
    replay,
    reset_backend,
    set_backend,
)

from _replay_builders import llm, priced, turn


@pytest.fixture(autouse=True)
def _isolated_backend():
    """Guard every test against a leaked set_backend() (mirrors test_replay)."""
    reset_backend()
    yield
    reset_backend()


def _echo_backend(**overrides):
    """Identity-replay backend; kwargs override ReplayedDecision fields so a
    test can vary exactly the channel under test (text or decision_chosen)."""

    def backend(context, original_span, variant):
        fields = dict(
            model=original_span.gen_ai_request_model,
            output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
        )
        fields.update(overrides)
        return ReplayedDecision(**fields)

    return backend


# --------------------------------------------------------------------------- #
# Bounded kinds: the gate compares the DECISION, not the string.              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("kind, original_label, candidates", [
    (DecisionKind.route, "billing_dispute", ["billing_dispute", "other"]),
    (DecisionKind.compose, "inform", ["inform"]),
    (DecisionKind.tool_select, "lookup_account", ["lookup_account"]),
    (DecisionKind.escalate_check, "continue", ["continue", "escalate"]),
])
def test_same_label_paraphrase_is_not_divergent(kind, original_label, candidates):
    """THE case difflib got wrong: completely different words, same decision.
    Under the old text gate this exact shape was 217/217 divergent on real
    replies."""
    span = llm("l0", decision_kind=kind, decision_chosen=original_label,
               output_text="Order status. Let me look into that for you.")
    span = span.model_copy(update={"decision_candidates": candidates})
    set_backend(_echo_backend(
        output_text="Certainly, one moment while I check the details of your request."))
    pt = priced(turn(0, llm_spans=[span]))
    trial = replay(pt, VariantSpec(model_routing={kind.value: "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"
    assert trial.outcome_preserved is not None


@pytest.mark.parametrize("kind, original_label, replayed_label, candidates", [
    (DecisionKind.route, "billing_dispute", "other", ["billing_dispute", "other"]),
    (DecisionKind.compose, "inform", "close_call", ["inform", "close_call"]),
    (DecisionKind.tool_select, "lookup_account", "retrieve_kb_article",
     ["lookup_account", "retrieve_kb_article"]),
    (DecisionKind.escalate_check, "continue", "escalate", ["continue", "escalate"]),
])
def test_different_parsed_label_is_divergent(kind, original_label, replayed_label,
                                             candidates):
    """A different decision is a fork even when the words are identical -- the
    converse blind spot of the text gate."""
    span = llm("l0", decision_kind=kind, decision_chosen=original_label,
               output_text="Order status. Let me look into that for you.")
    span = span.model_copy(update={"decision_candidates": candidates})
    set_backend(_echo_backend(decision_chosen=replayed_label))
    pt = priced(turn(0, llm_spans=[span]))
    trial = replay(pt, VariantSpec(model_routing={kind.value: "gpt-5-nano"}), from_turn=0)
    assert trial.status == "divergent"
    assert trial.outcome_preserved is None
    assert trial.delta_cost is None


@pytest.mark.parametrize("kind, original_label, candidates", [
    (DecisionKind.route, "billing_dispute", ["billing_dispute", "other"]),
    (DecisionKind.compose, "inform", ["inform"]),
])
def test_unparseable_replayed_reply_is_divergent(kind, original_label, candidates):
    """Raw passthrough (no in-vocab label) cannot confirm the same decision:
    divergent, never folded as preserved."""
    span = llm("l0", decision_kind=kind, decision_chosen=original_label,
               output_text="Order status. Let me look into that for you.")
    span = span.model_copy(update={"decision_candidates": candidates})
    raw_utterance = "I will go ahead and take care of that for you right away."
    set_backend(_echo_backend(output_text=raw_utterance, decision_chosen=raw_utterance))
    pt = priced(turn(0, llm_spans=[span]))
    trial = replay(pt, VariantSpec(model_routing={kind.value: "gpt-5-nano"}), from_turn=0)
    assert trial.status == "divergent"
    assert trial.outcome_preserved is None


# --------------------------------------------------------------------------- #
# slot_fill: the content path is UNCHANGED (W3-C regression guards).          #
# --------------------------------------------------------------------------- #

def test_slot_fill_label_channel_is_ignored():
    """slot_fill keeps the content path: a changed decision_chosen with
    IDENTICAL text is still non-divergent (the label gate must NOT extend
    here -- single-label kind, verdict rides on content)."""
    span = llm("l0", decision_kind=DecisionKind.slot_fill, decision_chosen="request_slot",
               output_text="Could you confirm the email on the account?")
    set_backend(_echo_backend(decision_chosen="something-else-entirely"))
    pt = priced(turn(0, llm_spans=[span]))
    trial = replay(pt, VariantSpec(model_routing={"slot_fill": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "ok"


def test_slot_fill_diverges_on_low_similarity_text_as_today():
    """slot_fill's divergence still comes from the content/_similarity path."""
    span = llm("l0", decision_kind=DecisionKind.slot_fill, decision_chosen="request_slot",
               output_text="Could you confirm the email on the account?")
    set_backend(_echo_backend(output_text="Totally unrelated content entirely."))
    pt = priced(turn(0, llm_spans=[span]))
    trial = replay(pt, VariantSpec(model_routing={"slot_fill": "gpt-5-nano"}), from_turn=0)
    assert trial.status == "divergent"
    assert trial.outcome_preserved is None
