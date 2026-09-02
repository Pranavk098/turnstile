"""Tests for the trace-level checkpointed matrix runner
(turnstile_experiments.checkpoint_runner): it must reproduce run_matrix's
aggregates, resume from a checkpoint WITHOUT recomputing (never re-spending),
fail loudly on reserved variants, and tolerate a torn final checkpoint line."""
from __future__ import annotations

import json

import pytest

from turnstile_replay import MockBackend, reset_backend
from turnstile_schema import Trial, VariantSpec
from turnstile_schema.enums import DecisionKind

from turnstile_experiments import (
    REPRICING_VARIANTS,
    VARIANTS,
    CheckpointStore,
    run_matrix,
    run_matrix_checkpointed,
    run_matrix_checkpointed_detailed,
)

from _experiments_builders import llm, priced, turn


def _corpus():
    return [
        priced(turn(0, llm_spans=[llm("l0", decision_kind=DecisionKind.route)]),
               conversation_id=f"c{i}")
        for i in range(4)
    ]


def test_checkpointed_matches_run_matrix(tmp_path):
    reset_backend()
    corpus = _corpus()
    expected = run_matrix(corpus, VARIANTS)  # MockBackend, in-memory
    got = run_matrix_checkpointed(corpus, VARIANTS, tmp_path / "ck.jsonl")
    assert set(got) == set(expected)
    for name in expected:
        assert got[name].model_dump() == expected[name].model_dump()
    reset_backend()


def test_resume_does_not_recompute_or_respend(tmp_path):
    reset_backend()
    corpus = _corpus()
    ck = tmp_path / "ck.jsonl"

    first = run_matrix_checkpointed(corpus, VARIANTS, ck)  # populates checkpoint

    def _explode(context, original_span, variant):
        raise AssertionError("backend called on resume -- would re-spend")

    # Second run: every (variant, trace) is already checkpointed, so the backend
    # must never be invoked. Identical results, no recomputation.
    second = run_matrix_checkpointed(corpus, VARIANTS, ck, backend=_explode)
    for name in first:
        assert second[name].model_dump() == first[name].model_dump()
    reset_backend()


def test_partial_checkpoint_resumes_the_rest(tmp_path):
    reset_backend()
    corpus = _corpus()
    ck = tmp_path / "ck.jsonl"

    # Complete only the first two traces of the run, then resume: the backend
    # may be called for the remaining traces but NOT the completed ones.
    run_matrix_checkpointed(corpus[:2], VARIANTS, ck)
    completed = len(CheckpointStore(ck))
    assert completed == 2  # one variant x two traces

    called_ids = []

    def _spy(context, original_span, variant):
        called_ids.append(context.conversation_id)
        return MockBackend()(context, original_span, variant)

    run_matrix_checkpointed(corpus, VARIANTS, ck, backend=_spy)
    # Only the two not-yet-checkpointed traces should have hit the backend.
    assert set(called_ids) == {"c2", "c3"}
    reset_backend()


def test_reserved_variant_fails_loudly(tmp_path):
    # tts_chunking is the one field still without an execution path (the
    # barge-in acoustic track owns it) -- the checkpointed runner must refuse
    # it like run_matrix does.
    reset_backend()
    corpus = _corpus()
    with pytest.raises(NotImplementedError):
        run_matrix_checkpointed(
            corpus, {"tts_chunking_sentence": VariantSpec(tts_chunking="sentence")},
            tmp_path / "tts.jsonl")
    reset_backend()


def test_repricing_variant_fails_loudly(tmp_path):
    # prefix_caching executes via run_repricing_matrix, never the (possibly
    # paid) backend path -- there it would be a silent zero-delta no-op.
    reset_backend()
    corpus = _corpus()
    with pytest.raises(NotImplementedError, match="run_repricing_matrix"):
        run_matrix_checkpointed(corpus, REPRICING_VARIANTS, tmp_path / "repricing.jsonl")
    reset_backend()


def test_torn_final_line_is_tolerated(tmp_path):
    ck = tmp_path / "ck.jsonl"
    reset_backend()
    corpus = _corpus()
    run_matrix_checkpointed(corpus, VARIANTS, ck)
    good = len(CheckpointStore(ck))

    # Simulate a crash mid-write: append a truncated JSON line.
    with ck.open("a", encoding="utf-8") as f:
        f.write('{"key": "model_routing_gpt5_nano\\tcX", "trial": {"trace_i')

    store = CheckpointStore(ck)
    assert len(store) == good  # torn line skipped, valid trials intact
    reset_backend()


# --------------------------------------------------------------------------- #
# CR-B: the non-gated delta_cost_real_usage companion figure is checkpointed  #
# alongside the trial (without touching the frozen Trial schema) and survives #
# a resume -- resumed trials are never recomputed, so the figure must come    #
# back from the store.                                                        #
# --------------------------------------------------------------------------- #

def test_real_usage_companion_is_checkpointed_and_survives_resume(tmp_path):
    reset_backend()
    corpus = _corpus()
    ck = tmp_path / "ck.jsonl"

    first, first_real = run_matrix_checkpointed_detailed(corpus, VARIANTS, ck)
    # MockBackend's safe reroute keeps the original usage, so the real-usage
    # figure equals the gated rate-arbitrage figure -- both non-None.
    assert set(first_real) == set(VARIANTS)
    for name in first_real:
        assert first_real[name] is not None
        assert first_real[name] == pytest.approx(first[name].delta_cost_mean)

    # Resume with a backend that would re-spend if invoked: identical matrix
    # AND identical real-usage means, read back from the checkpoint file.
    def _explode(context, original_span, variant):
        raise AssertionError("backend called on resume -- would re-spend")

    second, second_real = run_matrix_checkpointed_detailed(
        corpus, VARIANTS, ck, backend=_explode)
    for name in first:
        assert second[name].model_dump() == first[name].model_dump()
        assert second_real[name] == pytest.approx(first_real[name])
    reset_backend()


def test_store_real_usage_accessor_and_legacy_records(tmp_path):
    reset_backend()
    corpus = _corpus()
    ck = tmp_path / "ck.jsonl"
    run_matrix_checkpointed_detailed(corpus, VARIANTS, ck)

    store = CheckpointStore(ck)
    key = "model_routing_gpt5_nano\tc0"
    assert store.get_real_usage(key) is not None
    assert store.get_real_usage("no-such-key") is None

    # Legacy pre-CR-B record (no companion field) reads back as None trial
    # side-effect free: rewrite one record without the field, reload.
    lines = ck.read_text(encoding="utf-8").splitlines()
    legacy = [ln for ln in lines if json.loads(ln)["key"] != key]
    rec = json.loads(next(ln for ln in lines if json.loads(ln)["key"] == key))
    legacy.append(json.dumps({"key": rec["key"], "trial": rec["trial"]}))
    ck.write_text("\n".join(legacy) + "\n", encoding="utf-8")
    store = CheckpointStore(ck)
    assert store.get_real_usage(key) is None
    assert store.get(key) is not None  # the trial itself still loads
    reset_backend()


# --------------------------------------------------------------------------- #
# Change B (concurrency): thread-safe checkpoint store, and a concurrent      #
# driver whose aggregates are byte-identical to the sequential path.          #
# --------------------------------------------------------------------------- #

def _trial(trace_id: str) -> Trial:
    return Trial(trace_id=trace_id, status="ok", delta_cost=-0.005,
                 delta_latency_ms=10.0, outcome_preserved=True)


def test_checkpoint_store_put_is_thread_safe_under_n_threads(tmp_path):
    import threading

    store = CheckpointStore(tmp_path / "ck.jsonl")
    n_threads, per_thread = 8, 10
    barrier = threading.Barrier(n_threads)

    def _worker(w: int) -> None:
        barrier.wait()  # maximize contention: all threads put simultaneously
        for t in range(per_thread):
            trial = _trial(f"w{w}-t{t}")
            store.put(f"w{w}-t{t}", trial, delta_cost_real_usage=-0.01 * (t + 1))

    threads = [threading.Thread(target=_worker, args=(w,)) for w in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    # Every line is valid, standalone JSON -- no interleaved/corrupt writes.
    lines = (tmp_path / "ck.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_threads * per_thread
    keys = set()
    for line in lines:
        rec = json.loads(line)  # raises on any interleaving corruption
        keys.add(rec["key"])
        assert store.get(rec["key"]) is not None
        assert store.get_real_usage(rec["key"]) is not None
    assert len(keys) == n_threads * per_thread  # all unique, none lost
    assert len(store) == n_threads * per_thread


def test_concurrent_matrix_is_byte_identical_to_sequential(tmp_path):
    import time

    reset_backend()
    # 8 traces x two route decisions each; the backend sleeps a trace-dependent
    # amount so completion order differs from corpus order under the pool.
    corpus = [
        priced(
            turn(0, llm_spans=[llm("l0", decision_kind=DecisionKind.route),
                               llm("l1", decision_kind=DecisionKind.route)]),
            turn(1, llm_spans=[llm("l2", decision_kind=DecisionKind.route)]),
            conversation_id=f"c{i}",
        )
        for i in range(8)
    ]

    def _jitter_backend(context, original_span, variant):
        time.sleep(0.01 * (int(context.conversation_id[1:]) % 4 + 1))
        return MockBackend()(context, original_span, variant)

    sequential = run_matrix_checkpointed(
        corpus, VARIANTS, tmp_path / "seq.jsonl", backend=_jitter_backend, max_workers=1)
    concurrent = run_matrix_checkpointed(
        corpus, VARIANTS, tmp_path / "conc.jsonl", backend=_jitter_backend, max_workers=8)

    assert set(concurrent) == set(VARIANTS)
    for name in VARIANTS:
        # Byte-identical aggregates: corpus-order assembly defeats completion
        # order (also pins identical bootstrap draws / percentiles).
        assert concurrent[name].model_dump() == sequential[name].model_dump()
    reset_backend()


def test_default_max_workers_one_is_the_sequential_path(tmp_path):
    reset_backend()
    corpus = _corpus()
    # No max_workers argument at all -- existing behavior, unchanged.
    result = run_matrix_checkpointed(corpus, VARIANTS, tmp_path / "ck.jsonl")
    expected = run_matrix(corpus, VARIANTS)
    for name in expected:
        assert result[name].model_dump() == expected[name].model_dump()
    reset_backend()


def test_resume_skips_checkpointed_traces_even_concurrently(tmp_path):
    import threading

    reset_backend()
    corpus = _corpus()
    ck = tmp_path / "ck.jsonl"
    run_matrix_checkpointed(corpus, VARIANTS, ck)  # populate

    lock = threading.Lock()
    called = []

    def _spy(context, original_span, variant):
        with lock:
            called.append(context.conversation_id)
        return MockBackend()(context, original_span, variant)

    result = run_matrix_checkpointed(corpus, VARIANTS, ck, backend=_spy, max_workers=4)
    assert called == []  # every (variant, trace) already checkpointed
    expected = run_matrix(corpus, VARIANTS)
    for name in expected:
        assert result[name].model_dump() == expected[name].model_dump()
    reset_backend()
