"""Tests for the preservation harness (turnstile_experiments.preservation, W3-C).

Deterministic preservation-measurement scaffolding: an authored
DecisionBackend (no model call, no network, no credit) drives the REAL
replay path over fixtures/preservation/ probes. These tests assert the
mechanism is non-trivial and decision-sensitive:

* preserve: benign paraphrase, still similar -> verdict unchanged (True).
* break (the money case): closing keyword dropped while staying similar ->
  verdict flips RESOLVED -> ABANDONED (False).
* divergent: dissimilar rewrite -> excluded from preservation (None).

Mechanism validation only -- NOT a measured preservation number (that awaits
the owner-gated paid run with the real OpenAI backend).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_replay import get_backend, reset_backend
from turnstile_schema import load_rates, load_trace
from turnstile_verdict import adjudicate

from turnstile_experiments.preservation import (
    BREAK_PROBE_ID,
    DIVERGENT_PROBE_ID,
    PRESERVE_PROBE_ID,
    PreservationBackend,
    from_turn_for,
    load_preservation_corpus,
    run_preservation,
)

ROOT = Path(__file__).parents[3]
PRESERVATION_DIR = ROOT / "fixtures" / "preservation"
RATES = load_rates(ROOT / "pricing" / "rates.yaml")


@pytest.fixture(autouse=True)
def _clean_backend():
    """reset_backend() in teardown so global backend state never leaks."""
    reset_backend()
    yield
    reset_backend()


def _rows_by_id(report):
    return {row["trace_id"]: row for row in report["rows"]}


# --------------------------------------------------------------------------- #
# Fixtures: valid v1.1 traces whose baselines resolve via clean close          #
# --------------------------------------------------------------------------- #

def test_preservation_fixtures_are_valid_v1_1_traces():
    paths = sorted(PRESERVATION_DIR.glob("*.json"))
    assert len(paths) >= 2  # minimal probe set
    for path in paths:
        trace = load_trace(path)  # raises ValidationError on any violation
        assert trace.conversation.end_reason.value == "caller_hangup"
        final_llm = trace.turns[-1].llm
        assert len(final_llm) == 1  # pivot is unambiguous: one final utterance
        assert final_llm[0].decision_kind.value == "slot_fill"


def test_all_baselines_adjudicate_resolved():
    for priced in load_preservation_corpus():
        verdict = adjudicate(priced)
        assert verdict.label.value == "RESOLVED", priced.trace.conversation.conversation_id


def test_pivot_selection_targets_the_verdict_load_bearing_final_utterance():
    # run_preservation replays from the final turn, so replay's pivot (the
    # FIRST replayed decision at/after from_turn) IS the final utterance --
    # the span _has_clean_close() reads. If this ever fails, the harness is
    # varying text the verdict never reads: STOP and flag, do not force it.
    for priced in load_preservation_corpus():
        from_turn = from_turn_for(priced)
        assert from_turn == priced.trace.turns[-1].turn_index
        targets = [
            span for turn in priced.trace.turns
            if turn.turn_index >= from_turn for span in turn.llm
        ]
        assert len(targets) == 1
        assert targets[0].span_id == priced.trace.turns[-1].llm[0].span_id


# --------------------------------------------------------------------------- #
# The three contrasting cases                                                  #
# --------------------------------------------------------------------------- #

def test_preserve_case_paraphrase_keeps_verdict():
    row = _rows_by_id(run_preservation())[PRESERVE_PROBE_ID]
    assert row["similarity"] >= 0.75
    assert row["status"] == "ok"
    assert row["original_label"] == "RESOLVED"
    assert row["new_label"] == "RESOLVED"
    assert row["outcome_preserved"] is True


def test_break_case_drop_closing_flips_verdict_while_staying_similar():
    row = _rows_by_id(run_preservation())[BREAK_PROBE_ID]
    # THE CRUX: similar enough to be re-adjudicated, different enough to flip.
    assert row["similarity"] >= 0.75, (
        f"break variant diverged (similarity={row['similarity']:.4f}); "
        "the flip would be excluded instead of counted -- STOP and flag"
    )
    assert row["status"] == "ok"
    assert row["original_label"] == "RESOLVED"
    assert row["new_label"] == "ABANDONED"
    assert row["outcome_preserved"] is False


def test_divergent_case_is_excluded_from_preservation():
    row = _rows_by_id(run_preservation())[DIVERGENT_PROBE_ID]
    assert row["similarity"] < 0.75
    assert row["status"] == "divergent"
    assert row["outcome_preserved"] is None
    assert row["new_label"] is None


# --------------------------------------------------------------------------- #
# Aggregate: a real function of the decision, non-vacuous divergence          #
# --------------------------------------------------------------------------- #

def test_aggregate_rates_prove_decision_sensitivity():
    report = run_preservation()
    assert report["n"] == 3
    # 1 preserved + 1 flipped over 2 non-divergent probes: strictly between
    # 0 and 1 proves preservation is a function of the decision, not
    # structurally 1.0.
    assert 0.0 < report["preservation_rate"] < 1.0
    assert report["preservation_rate"] == pytest.approx(0.5)
    # 1 divergent of 3: divergence fires on real baseline text (non-vacuous)
    # without swallowing the probe set.
    assert report["divergence_rate"] < 1.0
    assert report["divergence_rate"] == pytest.approx(1 / 3)


def test_new_labels_agree_with_outcome_preserved_flags():
    # Cross-check on the report's re-adjudication mirror: the independently
    # re-adjudicated new_label must equal the original exactly when replay's
    # own outcome_preserved flag says so. Any drift here means the mirror no
    # longer matches what replay adjudicated internally.
    for row in run_preservation()["rows"]:
        if row["status"] == "divergent":
            continue
        assert (row["new_label"] == row["original_label"]) is row["outcome_preserved"]


# --------------------------------------------------------------------------- #
# Backend hygiene                                                               #
# --------------------------------------------------------------------------- #

def test_run_preservation_restores_the_previous_backend():
    sentinel = PreservationBackend()
    from turnstile_replay import set_backend
    set_backend(sentinel)
    run_preservation()
    assert get_backend() is sentinel


def test_global_backend_state_does_not_leak():
    run_preservation(backend=PreservationBackend())
    reset_backend()
    from turnstile_replay import MockBackend
    assert isinstance(get_backend(), MockBackend)


def test_default_backend_is_the_authored_one():
    report = run_preservation()  # backend=None -> authored PreservationBackend
    assert report["n"] == 3
    assert _rows_by_id(report)[BREAK_PROBE_ID]["outcome_preserved"] is False
