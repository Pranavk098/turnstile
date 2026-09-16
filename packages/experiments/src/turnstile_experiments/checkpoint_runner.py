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
from concurrent.futures import ThreadPoolExecutor
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
from turnstile_replay import aggregate_experiment

from turnstile_experiments.guard import assert_backend_executable, assert_variant_executable


def _trace_id(pt: PricedTrace) -> str:
    return pt.trace.conversation.conversation_id


def variant_extras(
    store: CheckpointStore, variant_name: str, corpus: list[PricedTrace]
) -> dict:
    """Build the result-JSON side blocks for one variant from the checkpoint
    store (the experiment-hardening work).

    Returns ``{"divergent_records": [...], "n_truncated": int,
    "truncated_exemplars": [...]}`` where each divergent record carries
    ``trace_id`` / ``forked_label`` / ``forked_text`` / ``finish_reason`` and
    each truncated exemplar carries ``trace_id`` / ``finish_reason`` plus the
    reasoning/content split (``reasoning_tokens`` / ``output_tokens``).

    These live ALONGSIDE the frozen ``ExperimentResult`` in the CLI's result
    JSON (never inside it): truncated trials are already excluded from every
    aggregate via ``status="excluded"`` (out of numerator AND denominator),
    and divergent records let ``analyze_forks`` run with no sidecar. Mock
    runs yield empty records and ``n_truncated == 0``."""
    divergent_records: list[dict] = []
    truncated_exemplars: list[dict] = []
    for pt in corpus:
        trace_id = _trace_id(pt)
        key = f"{variant_name}\t{trace_id}"
        if store.is_truncated(key):
            trunc = store.get_truncation(key) or {}
            truncated_exemplars.append({
                "trace_id": trace_id,
                "finish_reason": trunc.get("finish_reason", "length"),
                "reasoning_tokens": trunc.get("reasoning_tokens"),
                "output_tokens": trunc.get("output_tokens"),
            })
            continue
        fork = store.get_fork(key)
        if fork is not None:
            divergent_records.append({
                "trace_id": trace_id,
                "forked_label": fork.get("forked_label"),
                "forked_text": fork.get("forked_text"),
                "finish_reason": fork.get("finish_reason"),
            })
    # Corpus order is deterministic; sort records by trace_id for stable JSON.
    divergent_records.sort(key=lambda r: r["trace_id"])
    truncated_exemplars.sort(key=lambda r: r["trace_id"])
    return {
        "divergent_records": divergent_records,
        "n_truncated": len(truncated_exemplars),
        "truncated_exemplars": truncated_exemplars,
    }


class CheckpointStore:
    """Append-only JSON-Lines store of completed trials, keyed
    ``"{variant}\\t{trace_id}"``. Tolerates a torn trailing line from a crash
    mid-write (that trial is simply recomputed). Records also carry the
    non-gated ``delta_cost_real_usage`` companion figure (CR-B) next to the
    ``Trial`` -- without polluting the frozen ``Trial`` schema -- so a resumed
    run can still report it for trials it did not recompute. Legacy records
    without the field read back as ``None``.

    Experiment-hardening: records additionally carry the fork/truncation
    metadata the frozen ``Trial`` cannot hold (same alongside-not-inside
    pattern): divergent trials persist ``forked_label`` / ``forked_text`` /
    ``finish_reason`` so ``analyze_forks`` needs no sidecar; truncated trials
    (``finish_reason == "length"``) persist ``truncated`` plus the
    reasoning/content split. Legacy records without these keys read back as
    no-fork / not-truncated."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._done: dict[str, Trial] = {}
        self._real_usage: dict[str, float] = {}
        self._forks: dict[str, dict] = {}
        self._truncated: dict[str, dict] = {}
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
                    forked_label = rec.get("forked_label")
                    if forked_label is not None:
                        self._forks[rec["key"]] = {
                            "forked_label": forked_label,
                            "forked_text": rec.get("forked_text"),
                            "finish_reason": rec.get("finish_reason"),
                        }
                    elif rec.get("finish_reason") is not None and self._done[rec["key"]].status == "divergent":
                        # Divergent record with a finish reason but no label
                        # (should not happen from new writers; kept for
                        # forward-compat reads).
                        self._forks[rec["key"]] = {
                            "forked_label": None,
                            "forked_text": rec.get("forked_text"),
                            "finish_reason": rec.get("finish_reason"),
                        }
                    if rec.get("truncated") is True:
                        self._truncated[rec["key"]] = {
                            "finish_reason": rec.get("finish_reason", "length"),
                            "reasoning_tokens": rec.get("truncated_reasoning_tokens"),
                            "output_tokens": rec.get("truncated_output_tokens"),
                        }
                except (json.JSONDecodeError, KeyError):
                    # Torn final line from an interrupted write -> skip; the
                    # trial it half-recorded gets recomputed this run.
                    continue

    def get(self, key: str) -> Trial | None:
        return self._done.get(key)

    def get_real_usage(self, key: str) -> float | None:
        """The stored ``delta_cost_real_usage`` for `key`, or ``None``."""
        return self._real_usage.get(key)

    def get_fork(self, key: str) -> dict | None:
        """The stored fork detail for `key` (``{"forked_label",
        "forked_text", "finish_reason"}``), or ``None`` when the trial did
        not diverge or the record predates fork-persistence."""
        return self._forks.get(key)

    def is_truncated(self, key: str) -> bool:
        """Whether `key`'s trial was flagged truncated (``finish_reason ==
        "length"``). Legacy records read back as ``False``."""
        return key in self._truncated

    def get_truncation(self, key: str) -> dict | None:
        """The stored truncation detail for `key` (``{"finish_reason",
        "reasoning_tokens", "output_tokens"}``), or ``None``."""
        return self._truncated.get(key)

    def _stage_locked(self, key: str, trial: Trial,
                      delta_cost_real_usage: float | None = None,
                      *,
                      forked_label: str | None = None,
                      forked_text: str | None = None,
                      finish_reason: str | None = None,
                      truncated: bool = False,
                      truncated_reasoning_tokens: int | None = None,
                      truncated_output_tokens: int | None = None) -> dict:
        """Update the in-memory dicts and build the JSONL record for one
        trial. Caller MUST hold ``self._lock``. Shared by ``put`` and
        ``put_batch`` so a batched record is byte-identical to a single-put
        record."""
        self._done[key] = trial
        if delta_cost_real_usage is not None:
            self._real_usage[key] = delta_cost_real_usage
        if forked_label is not None:
            self._forks[key] = {
                "forked_label": forked_label,
                "forked_text": forked_text,
                "finish_reason": finish_reason,
            }
        if truncated:
            self._truncated[key] = {
                "finish_reason": finish_reason or "length",
                "reasoning_tokens": truncated_reasoning_tokens,
                "output_tokens": truncated_output_tokens,
            }
        rec: dict = {"key": key, "trial": trial.model_dump()}
        if delta_cost_real_usage is not None:
            rec["delta_cost_real_usage"] = delta_cost_real_usage
        if forked_label is not None:
            rec["forked_label"] = forked_label
            rec["forked_text"] = forked_text
            rec["finish_reason"] = finish_reason
        if truncated:
            rec["truncated"] = True
            # When a truncated trial also carries a fork label (should not
            # happen -- truncation takes precedence over divergence), the
            # fork block above already stored finish_reason; ensure the
            # truncation block still records it.
            rec["finish_reason"] = finish_reason or "length"
            rec["truncated_reasoning_tokens"] = truncated_reasoning_tokens
            rec["truncated_output_tokens"] = truncated_output_tokens
        elif finish_reason is not None and forked_label is None and trial.status == "divergent":
            # Divergent trial whose backend returned no label detail but
            # did return a finish reason (defensive; new writers always
            # send the label): persist the reason so the exemplar block
            # still records it.
            rec["finish_reason"] = finish_reason
        return rec

    def _flush_locked(self, recs: list[dict]) -> None:
        """Append already-staged records with ONE flush+fsync. Caller MUST
        hold ``self._lock``. Group commit: one fsync covers the whole batch
        instead of one per trial."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def put(self, key: str, trial: Trial,
            delta_cost_real_usage: float | None = None,
            *,
            forked_label: str | None = None,
            forked_text: str | None = None,
            finish_reason: str | None = None,
            truncated: bool = False,
            truncated_reasoning_tokens: int | None = None,
            truncated_output_tokens: int | None = None) -> None:
        with self._lock:
            rec = self._stage_locked(
                key, trial, delta_cost_real_usage,
                forked_label=forked_label, forked_text=forked_text,
                finish_reason=finish_reason, truncated=truncated,
                truncated_reasoning_tokens=truncated_reasoning_tokens,
                truncated_output_tokens=truncated_output_tokens)
            self._flush_locked([rec])

    def put_batch(self, items: list[tuple[str, object]]) -> None:
        """Group-commit ``[(key, outcome)]`` (Day-3 Track C): stage every
        trial's record, then append + flush + fsync ONCE for the whole batch.

        Each record is byte-identical to what ``put`` would have written for
        the same outcome (same ``_stage_locked`` path); only the fsync
        frequency changes. The sequential path keeps per-trial ``put`` (a
        crash loses nothing already produced); the parallel path commits one
        worker chunk at a time (a crash loses at most the in-flight chunks,
        which resume recomputes -- keys are unique per trace, so resume
        still skips exactly the persisted trials and never double-counts).
        Torn-tail tolerance is unchanged: a partial batch write still ends
        in at most one torn line, which ``_load`` skips."""
        with self._lock:
            recs = [self._stage_locked(
                key,
                outcome.trial,  # type: ignore[attr-defined]
                getattr(outcome, "delta_cost_real_usage", None),
                forked_label=getattr(outcome, "forked_label", None),
                forked_text=getattr(outcome, "forked_text", None),
                finish_reason=getattr(outcome, "finish_reason", None),
                truncated=bool(getattr(outcome, "truncated", False)),
                truncated_reasoning_tokens=getattr(
                    outcome, "truncated_reasoning_tokens", None),
                truncated_output_tokens=getattr(
                    outcome, "truncated_output_tokens", None),
            ) for key, outcome in items]
            self._flush_locked(recs)

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

    Change B (audit 06 Sec.3/§6, Day-3 Track C): ``max_workers > 1`` runs the
    map step (per-trace ``replay``) on a ``ThreadPoolExecutor`` over the
    NOT-yet-checkpointed traces only -- completed keys skip exactly as the
    sequential loop does, so a resumed run never re-spends. The pending
    traces are split into at most ``max_workers`` CONTIGUOUS chunks (one task
    per worker, not one task per trace, so pool overhead stays flat as the
    corpus grows); each worker replays its chunk sequentially and the main
    thread group-commits each chunk's outcomes (``put_batch``: one fsync per
    chunk instead of one per trial -- the profiled hot path) in chunk order.
    The shared backend is safe across workers (the OpenAI client is
    thread-safe; ``replay`` reads globals + builds local state;
    ``CheckpointStore`` stays lock-guarded). DETERMINISM: chunks cover
    contiguous corpus ranges and are committed in corpus order, so the trial
    list, the checkpoint RECORDS, and the aggregates are byte-identical to
    the sequential path (the sequential path itself is untouched: per-trial
    ``put`` with per-trial fsync). Variants stay sequential (see
    ``run_matrix_checkpointed_detailed``). Resume semantics are unchanged: a
    crash loses at most the in-flight chunks, which resume recomputes."""
    assert_variant_executable(variant_name, variant)
    assert_backend_executable(variant_name, variant)

    keys = [f"{variant_name}\t{_trace_id(pt)}" for pt in corpus]
    trials: list[Trial | None] = [store.get(k) for k in keys]
    pending = [(i, pt) for i, (pt, t) in enumerate(zip(corpus, trials)) if t is None]

    def _record(i: int, pt: PricedTrace, outcome) -> None:
        store.put(
            keys[i], outcome.trial, outcome.delta_cost_real_usage,
            forked_label=getattr(outcome, "forked_label", None),
            forked_text=getattr(outcome, "forked_text", None),
            finish_reason=getattr(outcome, "finish_reason", None),
            truncated=bool(getattr(outcome, "truncated", False)),
            truncated_reasoning_tokens=getattr(outcome, "truncated_reasoning_tokens", None),
            truncated_output_tokens=getattr(outcome, "truncated_output_tokens", None),
        )
        trials[i] = outcome.trial

    if max_workers > 1 and pending:
        n_chunks = min(max_workers, len(pending))
        chunk_size = (len(pending) + n_chunks - 1) // n_chunks
        chunks = [pending[k * chunk_size:(k + 1) * chunk_size]
                  for k in range(n_chunks)]

        def _run_chunk(chunk: list[tuple[int, PricedTrace]]) -> list:
            return [
                (i, replay_with_real_usage_cost(
                    pt, variant, _earliest_applicable_turn(pt, variant)))
                for i, pt in chunk
            ]

        # executor.map yields chunk results IN chunk (corpus) order, so the
        # commit below is deterministic regardless of completion order: each
        # outcome fills its own corpus-indexed slot.
        with ThreadPoolExecutor(max_workers=n_chunks) as executor:
            for chunk, outcomes in zip(chunks, executor.map(_run_chunk, chunks)):
                store.put_batch([(keys[i], outcome) for i, outcome in outcomes])
                for i, outcome in outcomes:
                    trials[i] = outcome.trial
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
