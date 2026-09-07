"""Item 2 truncation policy at the experiments layer (TDD, written red).

finish_reason == "length" -> truncated (excluded from every aggregate, out
of numerator AND denominator), counted as n_truncated and listed in
truncated_exemplars with finish_reason + reasoning/content split. The cap is
NOT raised. Mock never truncates.
"""
from __future__ import annotations

import json

import pytest

from turnstile_replay import reset_backend
from turnstile_replay.backend import ReplayedDecision
from turnstile_schema import VariantSpec

from _experiments_builders import llm, priced, turn


@pytest.fixture(autouse=True)
def _clean_backend():
    reset_backend()
    yield
    reset_backend()


def _corpus():
    return [
        priced(turn(0, llm_spans=[llm("l0", input_tokens=500, output_tokens=15)]),
               conversation_id="c0"),
        priced(turn(0, llm_spans=[llm("l0", input_tokens=500, output_tokens=15)]),
               conversation_id="c1"),
        priced(turn(0, llm_spans=[llm("l0", input_tokens=500, output_tokens=15)]),
               conversation_id="c2"),
    ]


def _backend_with_clipped_c2(context, original_span, variant):
    if context.conversation_id == "c2":
        return ReplayedDecision(
            model="gpt-5-nano", output_text="Partial clipped reply",
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=256, reasoning_tokens=240,
            latency_ms=original_span.latency_ms,
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


def test_truncated_trial_excluded_from_aggregates_and_listed(tmp_path):
    from turnstile_experiments import run_matrix_checkpointed_detailed
    from turnstile_experiments.checkpoint_runner import (
        CheckpointStore,
        variant_extras,
    )

    corpus = _corpus()
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})
    ck = tmp_path / "ck.jsonl"
    matrix, _real = run_matrix_checkpointed_detailed(
        corpus, {"v": variant}, ck, backend=_backend_with_clipped_c2)
    result = matrix["v"]

    # Truncated c2 is out of n entirely (excluded, not divergent).
    assert result.n == 2
    assert result.divergent_exemplars == []
    # The two ok trials are full-preservation identity replays on the same
    # label, so the rate is over the non-truncated set only.
    assert result.outcome_preservation_rate == pytest.approx(1.0)

    store = CheckpointStore(ck)
    assert store.is_truncated("v\tc2") is True
    assert store.is_truncated("v\tc0") is False
    trunc = store.get_truncation("v\tc2")
    assert trunc is not None
    assert trunc["finish_reason"] == "length"
    assert trunc["reasoning_tokens"] == 240
    assert trunc["output_tokens"] == 256

    extras = variant_extras(store, "v", corpus)
    assert extras["n_truncated"] == 1
    assert len(extras["truncated_exemplars"]) == 1
    exemplar = extras["truncated_exemplars"][0]
    assert exemplar["trace_id"] == "c2"
    assert exemplar["finish_reason"] == "length"
    assert exemplar["reasoning_tokens"] == 240
    assert exemplar["output_tokens"] == 256
    assert extras["divergent_records"] == []


def test_no_truncation_on_identity_backend(tmp_path):
    """Control: without length finish reasons nothing is truncated and the
    enrichment blocks are empty (the mock-regression shape)."""
    from turnstile_experiments import run_matrix_checkpointed_detailed
    from turnstile_experiments.checkpoint_runner import (
        CheckpointStore,
        variant_extras,
    )

    def _ok(context, original_span, variant):
        return ReplayedDecision(
            model="gpt-5-nano", output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
            finish_reason="stop",
        )

    corpus = _corpus()
    ck = tmp_path / "ck.jsonl"
    matrix, _real = run_matrix_checkpointed_detailed(
        corpus, {"v": VariantSpec(model_routing={"route": "gpt-5-nano"})},
        ck, backend=_ok)
    assert matrix["v"].n == 3
    extras = variant_extras(CheckpointStore(ck), "v", corpus)
    assert extras["n_truncated"] == 0
    assert extras["truncated_exemplars"] == []
    assert extras["divergent_records"] == []


def test_truncated_checkpoint_round_trips_and_legacy_defaults_false(tmp_path):
    from turnstile_experiments.checkpoint_runner import CheckpointStore
    from turnstile_schema import Trial

    ck = tmp_path / "ck.jsonl"
    store = CheckpointStore(ck)
    trial = Trial(trace_id="c2", status="excluded", delta_cost=None,
                  delta_latency_ms=None, outcome_preserved=None)
    store.put("v\tc2", trial, None, finish_reason="length", truncated=True,
              truncated_reasoning_tokens=240, truncated_output_tokens=256)
    reloaded = CheckpointStore(ck)
    assert reloaded.is_truncated("v\tc2") is True
    trunc = reloaded.get_truncation("v\tc2")
    assert trunc["finish_reason"] == "length"

    # Legacy record without truncation keys defaults to not-truncated.
    store2_ck = tmp_path / "ck2.jsonl"
    store2 = CheckpointStore(store2_ck)
    store2.put("v\tc0", Trial(trace_id="c0", status="ok", delta_cost=0.0,
                               delta_latency_ms=0.0, outcome_preserved=True))
    assert CheckpointStore(store2_ck).is_truncated("v\tc0") is False


def test_cli_result_json_carries_truncation_blocks(tmp_path):
    """run_experiments CLI writes n_truncated / truncated_exemplars /
    divergent_records into each matrix variant block (alongside, never
    inside, the frozen ExperimentResult)."""
    import importlib.util
    import sys
    from pathlib import Path as _Path

    cli_path = _Path(__file__).resolve().parents[1] / "run_experiments.py"
    spec = importlib.util.spec_from_file_location("trunc_cli_check", cli_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    out = tmp_path / "results.json"
    module.main([
        "--n", "3", "--seed", "0",
        "--out", str(out),
        "--checkpoint", str(tmp_path / "ck.jsonl"),
    ])
    results = json.loads(out.read_text(encoding="utf-8"))
    for _name, block in results["matrix"].items():
        assert "divergent_records" in block
        assert "n_truncated" in block
        assert "truncated_exemplars" in block
        # Mock never truncates and (safe reroute) never diverges.
        assert block["n_truncated"] == 0
        assert block["truncated_exemplars"] == []
