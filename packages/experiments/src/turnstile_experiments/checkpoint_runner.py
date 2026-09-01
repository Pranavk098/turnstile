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
from turnstile_replay import DecisionBackend, MockBackend, get_backend, set_backend
from turnstile_replay.replay import _earliest_applicable_turn, replay
from turnstile_stats import aggregate_experiment

from turnstile_experiments.guard import assert_variant_executable


def _trace_id(pt: PricedTrace) -> str:
    return pt.trace.conversation.conversation_id


class CheckpointStore:
    """Append-only JSON-Lines store of completed trials, keyed
    ``"{variant}\\t{trace_id}"``. Tolerates a torn trailing line from a crash
    mid-write (that trial is simply recomputed)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._done: dict[str, Trial] = {}
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
                except (json.JSONDecodeError, KeyError):
                    # Torn final line from an interrupted write -> skip; the
                    # trial it half-recorded gets recomputed this run.
                    continue

    def get(self, key: str) -> Trial | None:
        return self._done.get(key)

    def put(self, key: str, trial: Trial) -> None:
        self._done[key] = trial
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "trial": trial.model_dump()}) + "\n")
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
    checkpointed (and resumed from ``store``). Guards executability first."""
    assert_variant_executable(variant_name, variant)
    trials: list[Trial] = []
    for pt in corpus:
        key = f"{variant_name}\t{_trace_id(pt)}"
        trial = store.get(key)
        if trial is None:
            trial = replay(pt, variant, _earliest_applicable_turn(pt, variant))
            store.put(key, trial)
        trials.append(trial)
    return aggregate_experiment(trials)


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
    for name, variant in variants.items():
        assert_variant_executable(name, variant)

    store = CheckpointStore(checkpoint_path)
    previous = get_backend()
    set_backend(backend if backend is not None else MockBackend())
    try:
        return {
            name: run_experiment_checkpointed(corpus, name, variant, store)
            for name, variant in variants.items()
        }
    finally:
        set_backend(previous)
