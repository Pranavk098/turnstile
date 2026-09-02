"""Trace-level, resumable matrix runner.

``turnstile_replay.experiment`` is ``[replay(t, variant, from_turn) for t in
traces]`` then ``aggregate_experiment(...)`` -- a single in-memory pass. For a
paid run that is thousands of sequential API calls over hours, a crash (or a
stalled call) at trace 1,600 of 1,733 throws away every dollar already spent.

This runner reproduces ``experiment()`` faithfully but persists each
``(variant, trace)`` ``Trial`` to a JSON-Lines checkpoint the instant it is
produced, and on restart REPLAYS FROM the checkpoint -- already-completed
trials are loaded, never recomputed, so a resumed run never re-spends on work
it already paid for. Granularity is per trace WITHIN a variant (not merely
between variants), because one variant is ~1,700 calls.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from turnstile_schema import ExperimentResult, PricedTrace, Trial, VariantSpec
from turnstile_replay import (
    DecisionBackend,
    MockBackend,
    get_backend,
    set_backend,
)
from turnstile_replay.replay import (
    _earliest_applicable_turn,
    replay_with_real_usage_cost,
)
from turnstile_stats import aggregate_experiment

from turnstile_experiments.guard import assert_backend_executable, assert_variant_executable


def _trace_id(pt: PricedTrace) -> str:
    return pt.trace.conversation.conversation_id


class CheckpointStore:
    """Append-only JSON-Lines store of completed trials, keyed
    ``"{variant}\\t{trace_id}"``. Tolerates a torn trailing line from a crash
    mid-write (that trial is simply recomputed). Records also carry the
    non-gated ``delta_cost_real_usage`` companion figure (CR-B) next to the
    ``Trial`` -- without polluting the frozen ``Trial`` schema -- so a resumed
    run can still report it for trials it did not recompute. Legacy records
    without the field read back as ``None``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._done: dict[str, Trial] = {}
        self._real_usage: dict[str, float] = {}
        # L-1 (audit 06 Sec.6.1): under a worker pool, put() calls race on the
        # append+fsync AND on the in-memory dicts. One lock guards both; keys
        # are unique per worker task, so no dedup logic is needed.
        self._lock = threading.Lock()
        if path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    self._done[rec["key"]] = Trial.model_validate(rec["trial"])
                    real_usage = rec.get("delta_cost_real_usage")
                    if real_usage is not None:
                        self._real_usage[rec["key"]] = real_usage
                except (json.JSONDecodeError, KeyError):
                    # Torn final line from an interrupted write -> skip; the
                    # trial it half-recorded gets recomputed this run.
                    continue

    def get(self, key: str) -> Trial | None:
        return self._done.get(key)

    def get_real_usage(self, key: str) -> float | None:
        """The stored ``delta_cost_real_usage`` for `key`, or ``None``."""
        return self._real_usage.get(key)

    def put(self, key: str, trial: Trial,
            delta_cost_real_usage: float | None = None) -> None:
        with self._lock:
            self._done[key] = trial
            if delta_cost_real_usage is not None:
                self._real_usage[key] = delta_cost_real_usage
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rec: dict = {"key": key, "trial": trial.model_dump()}
            if delta_cost_real_usage is not None:
                rec["delta_cost_real_usage"] = delta_cost_real_usage
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def __len__(self) -> int:
        with self._lock:
            return len(self._done)


def run_experiment_checkpointed(
    corpus: list[PricedTrace],
    variant_name: str,
    variant: VariantSpec,
    store: CheckpointStore,
    max_workers: int = 1,
) -> ExperimentResult:
    """``turnstile_replay.experiment(corpus, variant)`` with each trace's trial
    checkpointed (and resumed from ``store``). Guards executability first.
    Fresh trials are computed via ``replay_with_real_usage_cost`` so the
    non-gated companion figure is checkpointed alongside the trial (CR-B).

    Change B (audit 06 Sec.3/§6): ``max_workers > 1`` runs the map step
    (per-trace ``replay``) on a ``ThreadPoolExecutor`` over the
    NOT-yet-checkpointed traces only -- completed keys skip exactly as the
    sequential loop does, so a resumed run never re-spends. The shared
    backend is safe across workers (the OpenAI client is thread-safe;
    ``replay`` reads globals + builds local state; ``CheckpointStore.put``
    is lock-guarded). DETERMINISM: results are assembled in corpus order
    regardless of completion order, so aggregates are byte-identical to the
    sequential path."""
    assert_variant_executable(variant_name, variant)
    assert_backend_executable(variant_name, variant)

    keys = [f"{variant_name}\t{_trace_id(pt)}" for pt in corpus]
    trials: list[Trial | None] = [store.get(k) for k in keys]
    pending = [(i, pt) for i, (pt, t) in enumerate(zip(corpus, trials)) if t is None]

    def _record(i: int, pt: PricedTrace, outcome) -> None:
        store.put(keys[i], outcome.trial, outcome.delta_cost_real_usage)
        trials[i] = outcome.trial

    if max_workers > 1 and pending:
        pending_pts = dict(pending)  # corpus index -> trace
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    replay_with_real_usage_cost,
                    pt, variant, _earliest_applicable_turn(pt, variant),
                ): i
                for i, pt in pending
            }
            # Completion order is irrelevant: each future fills its own
            # corpus-indexed slot, so assembly is deterministic.
            for future in as_completed(futures):
                _record(futures[future], pending_pts[futures[future]], future.result())
    else:
        for i, pt in pending:
            outcome = replay_with_real_usage_cost(
                pt, variant, _earliest_applicable_turn(pt, variant))
            _record(i, pt, outcome)

    return aggregate_experiment([t for t in trials if t is not None])


def run_matrix_checkpointed_detailed(
    corpus: list[PricedTrace],
    variants: dict[str, VariantSpec],
    checkpoint_path: Path,
    backend: DecisionBackend | None = None,
    max_workers: int = 1,
) -> tuple[dict[str, ExperimentResult], dict[str, float | None]]:
    """``run_matrix_checkpointed`` plus, per variant, the mean non-gated
    ``delta_cost_real_usage`` over the corpus (CR-B) -- computed in corpus
    order from the store, so resumed trials contribute their checkpointed
    figure. ``None`` for a variant with no real-usage data (e.g. every trial
    resumed from a legacy pre-CR-B checkpoint).

    ``max_workers`` (Change B): worker count for each variant's per-trace
    map (see ``run_experiment_checkpointed``); variants themselves stay
    sequential (see ``run_experiment_checkpointed``); variants themselves stay
    sequential."""
    for name, variant in variants.items():
        assert_variant_executable(name, variant)
        assert_backend_executable(name, variant)

    store = CheckpointStore(checkpoint_path)
    previous = get_backend()
    set_backend(backend if backend is not None else MockBackend())
    try:
        matrix: dict[str, ExperimentResult] = {}
        real_usage_mean: dict[str, float | None] = {}
        for name, variant in variants.items():
            matrix[name] = run_experiment_checkpointed(
                corpus, name, variant, store, max_workers=max_workers)
            figures = [store.get_real_usage(f"{name}\t{_trace_id(pt)}") for pt in corpus]
            present = [v for v in figures if v is not None]
            real_usage_mean[name] = sum(present) / len(present) if present else None
        return matrix, real_usage_mean
    finally:
        set_backend(previous)


def run_matrix_checkpointed(
    corpus: list[PricedTrace],
    variants: dict[str, VariantSpec],
    checkpoint_path: Path,
    backend: DecisionBackend | None = None,
    max_workers: int = 1,
) -> dict[str, ExperimentResult]:
    """Checkpointed drop-in for ``turnstile_experiments.run_matrix``. Every
    variant is guarded (``assert_variant_executable``) BEFORE any backend call,
    so a reserved/no-op variant fails loudly instead of spending. Restores the
    previously-installed backend afterward, like ``run_matrix``."""
    return run_matrix_checkpointed_detailed(
        corpus, variants, checkpoint_path, backend=backend, max_workers=max_workers)[0]
