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

from turnstile_experiments.guard import assert_variant_executable


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
        return len(self._done)


def run_experiment_checkpointed(
    corpus: list[PricedTrace],
    variant_name: str,
    variant: VariantSpec,
    store: CheckpointStore,
) -> ExperimentResult:
    """``turnstile_replay.experiment(corpus, variant)`` with each trace's trial
    checkpointed (and resumed from ``store``). Guards executability first.
    Fresh trials are computed via ``replay_with_real_usage_cost`` so the
    non-gated companion figure is checkpointed alongside the trial (CR-B)."""
    assert_variant_executable(variant_name, variant)
    trials: list[Trial] = []
    for pt in corpus:
        key = f"{variant_name}\t{_trace_id(pt)}"
        trial = store.get(key)
        if trial is None:
            outcome = replay_with_real_usage_cost(
                pt, variant, _earliest_applicable_turn(pt, variant))
            store.put(key, outcome.trial, outcome.delta_cost_real_usage)
            trial = outcome.trial
        trials.append(trial)
    return aggregate_experiment(trials)


def run_matrix_checkpointed_detailed(
    corpus: list[PricedTrace],
    variants: dict[str, VariantSpec],
    checkpoint_path: Path,
    backend: DecisionBackend | None = None,
) -> tuple[dict[str, ExperimentResult], dict[str, float | None]]:
    """``run_matrix_checkpointed`` plus, per variant, the mean non-gated
    ``delta_cost_real_usage`` over the corpus (CR-B) -- computed in corpus
    order from the store, so resumed trials contribute their checkpointed
    figure. ``None`` for a variant with no real-usage data (e.g. every trial
    resumed from a legacy pre-CR-B checkpoint)."""
    for name, variant in variants.items():
        assert_variant_executable(name, variant)

    store = CheckpointStore(checkpoint_path)
    previous = get_backend()
    set_backend(backend if backend is not None else MockBackend())
    try:
        matrix: dict[str, ExperimentResult] = {}
        real_usage_mean: dict[str, float | None] = {}
        for name, variant in variants.items():
            matrix[name] = run_experiment_checkpointed(corpus, name, variant, store)
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
) -> dict[str, ExperimentResult]:
    """Checkpointed drop-in for ``turnstile_experiments.run_matrix``. Every
    variant is guarded (``assert_variant_executable``) BEFORE any backend call,
    so a reserved/no-op variant fails loudly instead of spending. Restores the
    previously-installed backend afterward, like ``run_matrix``."""
    return run_matrix_checkpointed_detailed(
        corpus, variants, checkpoint_path, backend=backend)[0]
