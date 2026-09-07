"""Wave-2 preservation-under-divergence RE-ANALYSIS entry (TDD, written red).

Runs the ground-truth intent oracle (``turnstile_verdict.fork_oracle``) over
the REAL forks recorded in an existing paid-matrix result JSON -- no new paid
calls, no corpus regeneration beyond the deterministic free one. The forked
labels come from a sidecar JSON (the paid runs did not persist them -- the
Item 1 data gap); a fork without a sidecar label is ``unrecorded`` and can
only be reported as undecidable-by-data, never guessed.

HARD SEPARATION BAR (structurally tested): the report is a MODELED figure
under its own key (``preservation_under_divergence_modeled``) with its own
tier label, and NEVER reuses the measured identity-preservation key
(``outcome_preservation_rate``) or folds into it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from turnstile_corpus import generate_corpus

from turnstile_experiments.preservation_divergence import analyze_forks, main

SEED = 8


def _result_with_forks(tmp_path: Path, fork_ids: list[str]) -> Path:
    """A minimal paid-result-shaped JSON whose divergent_exemplars point at
    REAL (deterministically regenerated) corpus traces that carry a route
    pivot, so the re-analysis exercises the true code path for free."""
    assert fork_ids, "need at least one fork"
    result = {
        "n_corpus": 5,
        "seed": SEED,
        "backend": "OpenAIBackend",
        "matrix": {
            "model_routing_gpt5_nano": {
                "n": len(fork_ids),
                "divergent_exemplars": fork_ids,
            }
        },
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def _route_pivot_ids() -> list[str]:
    """Deterministically pick the first two seed-8 corpus traces whose pivot
    (first llm span) is a route decision -- the real forks' shape."""
    ids = []
    for trace in generate_corpus(5, SEED):
        spans = [s for turn in trace.turns for s in turn.llm]
        if spans and spans[0].decision_kind.value == "route":
            ids.append(trace.conversation.conversation_id)
        if len(ids) == 2:
            break
    assert len(ids) == 2
    return ids


def _sidecar(tmp_path: Path, labels: dict[str, str]) -> Path:
    path = tmp_path / "sidecar.json"
    path.write_text(json.dumps(labels), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# The Item 1 data gap: no sidecar -> every fork is unrecorded-by-data.        #
# --------------------------------------------------------------------------- #

def test_without_sidecar_every_fork_is_unrecorded_and_modeled_is_none(tmp_path):
    fork_ids = _route_pivot_ids()
    report = analyze_forks(_result_with_forks(tmp_path, fork_ids))

    assert report["n_forks"] == 2
    assert report["n_unrecorded"] == 2
    assert report["n_decidable"] == 0
    assert report["preservation_under_divergence_modeled"] is None
    for row in report["rows"]:
        assert row["forked_label"] is None
        assert row["classification"] == "unrecorded"
        assert row["verdict"] is None


def test_sidecar_labels_drive_the_oracle(tmp_path):
    fork_ids = _route_pivot_ids()
    # First fork routes to a different registered scenario (decidable,
    # not preserved); second fork routes to "other" (undecidable -> None).
    labels = {fork_ids[0]: "refund", fork_ids[1]: "other"}
    report = analyze_forks(
        _result_with_forks(tmp_path, fork_ids),
        sidecar_path=_sidecar(tmp_path, labels),
    )

    by_id = {row["trace_id"]: row for row in report["rows"]}
    first_intent = by_id[fork_ids[0]]["intent"]
    assert by_id[fork_ids[0]]["verdict"] is (
        None if first_intent == "refund" else False)  # cross-intent rule
    assert by_id[fork_ids[1]]["verdict"] is None  # "other": no registry rule
    assert report["n_undecidable"] >= 1
    # The modeled figure is preserved/decidable over RECORDED forks only.
    if report["n_decidable"] > 0:
        assert report["preservation_under_divergence_modeled"] == pytest.approx(
            report["n_preserved"] / report["n_decidable"])


# --------------------------------------------------------------------------- #
# HARD SEPARATION BAR: modeled figure, own keys, never the measured one.      #
# --------------------------------------------------------------------------- #

def test_report_is_structurally_separate_from_the_measured_figure(tmp_path):
    report = analyze_forks(_result_with_forks(tmp_path, _route_pivot_ids()))

    # The measured identity-preservation key never appears in the report...
    assert "outcome_preservation_rate" not in report
    assert "preservation_rate" not in report
    # ...and the modeled figure lives under its own explicitly-labeled key.
    assert "preservation_under_divergence_modeled" in report
    assert "MODELED" in report["tier"]
    assert "never folded" in report["tier"]


def test_all_undecidable_forks_are_listed_not_guessed(tmp_path):
    fork_ids = _route_pivot_ids()
    labels = {fork_id: "other" for fork_id in fork_ids}
    report = analyze_forks(
        _result_with_forks(tmp_path, fork_ids),
        sidecar_path=_sidecar(tmp_path, labels),
    )
    assert report["n_undecidable"] == len(fork_ids)
    assert [row["trace_id"] for row in report["rows"]
            if row["classification"] == "undecidable"] == fork_ids
    assert report["preservation_under_divergence_modeled"] is None


def test_main_prints_the_report(tmp_path, capsys):
    fork_ids = _route_pivot_ids()
    main([
        "--result", str(_result_with_forks(tmp_path, fork_ids)),
        "--sidecar", str(_sidecar(tmp_path, {fork_ids[0]: "refund"})),
    ])
    printed = json.loads(capsys.readouterr().out)
    assert printed["n_forks"] == 2
    assert "preservation_under_divergence_modeled" in printed
