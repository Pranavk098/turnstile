"""Item 1 fork-persistence at the experiments layer (TDD, written red).

OpenAIBackend returns finish_reason; the checkpoint record round-trips
forked_label / forked_text / finish_reason; analyze_forks reads labels
directly from the result JSON with no sidecar (sidecar stays as legacy
override).
"""
from __future__ import annotations

import json
from pathlib import Path

from turnstile_replay import reset_backend
from turnstile_replay.backend import ReplayedDecision, ReplayContext
from turnstile_schema import VariantSpec
from turnstile_schema.enums import DecisionKind

from turnstile_experiments.openai_backend import OpenAIBackend

from _experiments_builders import llm, turn


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoiceFinish:
    def __init__(self, content: str, finish_reason: str | None) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponseFinish:
    def __init__(self, content, prompt_tokens, completion_tokens, finish_reason) -> None:
        self.choices = [_FakeChoiceFinish(content, finish_reason)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeCompletions:
    def __init__(self, response) -> None:
        self._response = response

    def create(self, **kwargs):
        return self._response


class _FakeChat:
    def __init__(self, completions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, response) -> None:
        self.completions = _FakeCompletions(response)
        self.chat = _FakeChat(self.completions)


def _ctx():
    return ReplayContext(
        conversation_id="c1", scenario_id="s", turn_index=0, turns_before=())


def test_openai_backend_returns_finish_reason(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    backend = OpenAIBackend(
        client=_FakeClient(_FakeResponseFinish("hello", 10, 20, "stop")))
    decision = backend(
        _ctx(), llm("l1", decision_kind=DecisionKind.route, model="gpt-5"),
        VariantSpec())
    assert decision.finish_reason == "stop"


def test_openai_backend_returns_length_finish_reason(monkeypatch):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    backend = OpenAIBackend(
        client=_FakeClient(_FakeResponseFinish("clipped", 10, 256, "length")))
    decision = backend(
        _ctx(), llm("l1", decision_kind=DecisionKind.route, model="gpt-5"),
        VariantSpec())
    assert decision.finish_reason == "length"


def test_checkpoint_round_trips_fork_fields(tmp_path):
    from turnstile_experiments.checkpoint_runner import CheckpointStore
    from turnstile_schema import Trial

    ck = tmp_path / "ck.jsonl"
    store = CheckpointStore(ck)
    trial = Trial(trace_id="c9", status="divergent", delta_cost=None,
                  delta_latency_ms=None, outcome_preserved=None)
    store.put("v\tc9", trial, None,
              forked_label="other", forked_text="forked utterance",
              finish_reason="stop")

    reloaded = CheckpointStore(ck)
    assert reloaded.get("v\tc9") is not None
    fork = reloaded.get_fork("v\tc9")
    assert fork is not None
    assert fork["forked_label"] == "other"
    assert fork["forked_text"] == "forked utterance"
    assert fork["finish_reason"] == "stop"
    assert reloaded.is_truncated("v\tc9") is False


def test_checkpoint_legacy_record_without_fork_reads_as_none(tmp_path):
    from turnstile_experiments.checkpoint_runner import CheckpointStore
    from turnstile_schema import Trial

    ck = tmp_path / "ck.jsonl"
    store = CheckpointStore(ck)
    trial = Trial(trace_id="c1", status="divergent", delta_cost=None,
                  delta_latency_ms=None, outcome_preserved=None)
    store.put("v\tc1", trial)  # legacy shape: no fork kwargs
    # Rewrite as a bare legacy record (no fork keys at all).
    rec = json.loads(ck.read_text(encoding="utf-8").splitlines()[0])
    assert "forked_label" not in rec
    reloaded = CheckpointStore(ck)
    assert reloaded.get_fork("v\tc1") is None
    assert reloaded.is_truncated("v\tc1") is False


def _route_pivot_ids():
    from turnstile_corpus import generate_corpus

    ids = []
    for trace in generate_corpus(5, 8):
        spans = [s for turn in trace.turns for s in turn.llm]
        if spans and spans[0].decision_kind.value == "route":
            ids.append(trace.conversation.conversation_id)
        if len(ids) == 2:
            break
    assert len(ids) == 2
    return ids


def _result_with_divergent_records(tmp_path: Path, fork_ids, labels_by_id):
    result = {
        "n_corpus": 5,
        "seed": 8,
        "backend": "OpenAIBackend",
        "matrix": {
            "model_routing_gpt5_nano": {
                "n": len(fork_ids),
                "divergent_exemplars": fork_ids,
                "divergent_records": [
                    {"trace_id": tid,
                     "forked_label": labels_by_id[tid],
                     "forked_text": f"text for {tid}",
                     "finish_reason": "stop"}
                    for tid in fork_ids
                ],
            }
        },
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def test_analyze_forks_reads_labels_from_result_json_without_sidecar(tmp_path):
    from turnstile_experiments.preservation_divergence import analyze_forks

    fork_ids = _route_pivot_ids()
    # "other" is registry-undecidable; use a real cross-intent label for at
    # least one fork so the oracle has something decidable to judge.
    first_intent = None
    from turnstile_corpus import generate_corpus

    for trace in generate_corpus(5, 8):
        if trace.conversation.conversation_id == fork_ids[0]:
            first_intent = trace.conversation.scenario_id
            break
    other_intent = "refund" if first_intent != "refund" else "billing"
    labels = {fork_ids[0]: other_intent, fork_ids[1]: "other"}
    report = analyze_forks(_result_with_divergent_records(tmp_path, fork_ids, labels))
    assert report["n_forks"] == 2
    assert report["n_unrecorded"] == 0
    by_id = {row["trace_id"]: row for row in report["rows"]}
    assert by_id[fork_ids[0]]["forked_label"] == other_intent
    assert by_id[fork_ids[0]]["classification"] in ("preserved", "not_preserved")


def test_sidecar_overrides_result_json_labels(tmp_path):
    from turnstile_experiments.preservation_divergence import analyze_forks

    fork_ids = _route_pivot_ids()
    labels = {tid: "other" for tid in fork_ids}
    result_path = _result_with_divergent_records(tmp_path, fork_ids, labels)
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(json.dumps({fork_ids[0]: "refund"}), encoding="utf-8")
    report = analyze_forks(result_path, sidecar_path=sidecar)
    by_id = {row["trace_id"]: row for row in report["rows"]}
    assert by_id[fork_ids[0]]["forked_label"] == "refund"
    # Untouched fork keeps its result-JSON label.
    assert by_id[fork_ids[1]]["forked_label"] == "other"


def test_fork_inducing_backend_produces_self_documenting_checkpoint(tmp_path):
    """End-to-end (no paid calls): a fork-inducing fake backend through the
    checkpointed runner persists fork fields so analyze_forks needs no
    sidecar on the enriched result JSON."""
    from turnstile_experiments import run_matrix_checkpointed_detailed
    from turnstile_experiments.checkpoint_runner import (
        CheckpointStore,
        variant_extras,
    )

    from _experiments_builders import priced

    reset_backend()
    corpus = [
        priced(turn(0, llm_spans=[llm("l0", decision_chosen="billing_dispute")]),
               conversation_id="c1"),
        priced(turn(0, llm_spans=[llm("l0", decision_chosen="billing_dispute")]),
               conversation_id="c2"),
    ]
    variant = VariantSpec(model_routing={"route": "gpt-5-nano"})

    def _fork(context, original_span, variant_spec):
        if context.conversation_id == "c2":
            return ReplayedDecision(
                model="gpt-5-nano", output_text="forked utterance",
                decision_chosen="other",
                input_tokens=original_span.input_tokens,
                output_tokens=original_span.output_tokens,
                latency_ms=original_span.latency_ms,
                finish_reason="stop",
            )
        return ReplayedDecision(
            model="gpt-5-nano", output_text=original_span.output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            latency_ms=original_span.latency_ms,
            finish_reason="stop",
        )

    ck = tmp_path / "ck.jsonl"
    matrix, _real = run_matrix_checkpointed_detailed(
        corpus, {"v": variant}, ck, backend=_fork)
    assert matrix["v"].divergent_exemplars == ["c2"]

    store = CheckpointStore(ck)
    fork = store.get_fork("v\tc2")
    assert fork is not None
    assert fork["forked_label"] == "other"
    assert fork["forked_text"] == "forked utterance"
    assert fork["finish_reason"] == "stop"
    assert store.get_fork("v\tc1") is None

    # The CLI enrichment helper builds the result-JSON block from the store.
    extras = variant_extras(store, "v", corpus)
    assert extras["divergent_records"][0]["trace_id"] == "c2"
    assert extras["divergent_records"][0]["forked_label"] == "other"
    reset_backend()
