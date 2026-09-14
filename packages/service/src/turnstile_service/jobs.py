"""Bounded in-process experiment jobs (PRD 03 §4.2): non-blocking at volume.

An asyncio task runs the EXISTING experiment path (``map_trials`` +
``aggregate_experiment`` -- the exact pair ``experiment()`` composes, so the
aggregate can never drift from the sequential path) in a worker thread, over
priced traces the endpoint prepared synchronously. Results carry the same
``ExperimentResult`` shape the CLI produces plus the §8.3 gate verdict.

Bounds (all constructor-injectable for tests; module constants are the
production values):

* at most ``max_running`` experiments execute at once; submissions past
  ``max_active`` queued+running jobs are rejected (HTTP 429) and never touch
  the engine;
* at most ``max_stored`` job records live in memory; the oldest finished job
  is evicted first, then anything expired past ``ttl_seconds``;
* unknown or evicted ids read as 404 ("ephemeral" is part of the API).

$0 guard: the worker refuses to run unless the process backend is the
deterministic ``MockBackend`` -- global backend state is the one place a
paid call could sneak in, so the job errors loudly instead of running.

Threading: dict mutations take a lock; status transitions happen on the
event loop (task callbacks), never in worker threads.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from turnstile_replay import (
    MockBackend,
    aggregate_experiment,
    get_backend,
    map_trials,
    wilson_interval,
)

#: Production bounds: a free-tier container runs small, honest work.
MAX_RUNNING_JOBS = 2
MAX_ACTIVE_JOBS = 8
MAX_STORED_JOBS = 32
JOB_TTL_SECONDS = 900

GATE_PRESERVATION_MIN = 0.95
MOCK_BACKEND_PROVENANCE = (
    "MockBackend variant sweep (mechanism, not a measured production rate). "
    "Deterministic $0 replay; no live model call. A variant enters proven "
    "savings only when outcome_preservation_rate >= 0.95 AND the bootstrap "
    "95% CI upper bound on delta_cost is < 0 (PRD §8.3)."
)


def passes_gate(result: Any) -> bool:
    """The canonical §8.3 gate, mirrored from
    ``turnstile_experiments.margin._passes_gate`` (which owns it): preservation
    at bar and a strictly-negative savings CI. Mirrored -- not imported -- so
    the service never pulls the experiments package's paid-capable backend
    stack into its process; agreement with the canonical gate is asserted by
    test."""
    _ci_lo, ci_hi = result.delta_cost_ci95
    return result.outcome_preservation_rate >= GATE_PRESERVATION_MIN and ci_hi < 0.0


@dataclass
class Job:
    """One experiment submission and its lifecycle."""

    job_id: str
    status: str  # queued | running | done | error
    variant: dict
    n_calls: int
    rates_sha: str
    baselines_sha: str
    created_monotonic: float = field(default_factory=time.monotonic)
    result: dict | None = None
    error: str | None = None

    def public(self) -> dict:
        """The GET body: status always, result/error when terminal."""
        body: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "variant": self.variant,
            "n_calls": self.n_calls,
        }
        if self.result is not None:
            body["result"] = self.result
        if self.error is not None:
            body["error"] = self.error
        return body


class JobStoreFull(Exception):
    """Submission past the active-job cap (HTTP 429, engine never runs)."""


class JobStore:
    """Bounded in-memory job registry + runner."""

    def __init__(self, *, max_running: int = MAX_RUNNING_JOBS,
                 max_active: int = MAX_ACTIVE_JOBS,
                 max_stored: int = MAX_STORED_JOBS,
                 ttl_seconds: float = JOB_TTL_SECONDS) -> None:
        self._max_running = max_running
        self._max_active = max_active
        self._max_stored = max_stored
        self._ttl = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(max_running)

    # -- registry ------------------------------------------------------

    def _evict_locked(self, now: float) -> None:
        expired = [jid for jid, job in self._jobs.items()
                   if now - job.created_monotonic > self._ttl]
        for jid in expired:
            del self._jobs[jid]
        while len(self._jobs) > self._max_stored:
            oldest_done = next(
                (jid for jid, job in self._jobs.items()
                 if job.status in ("done", "error")),
                None,
            )
            victim = oldest_done if oldest_done is not None else next(
                iter(self._jobs))
            del self._jobs[victim]

    def _active_locked(self) -> int:
        return sum(1 for job in self._jobs.values()
                   if job.status in ("queued", "running"))

    def get(self, job_id: str) -> Job | None:
        """A live job record, or None when unknown/evicted (HTTP 404)."""
        with self._lock:
            self._evict_locked(time.monotonic())
            return self._jobs.get(job_id)

    def active_count(self) -> int:
        """Queued + running jobs (capacity introspection for tests)."""
        with self._lock:
            return self._active_locked()

    # -- submission ----------------------------------------------------

    def submit(self, *, variant: dict, n_calls: int, rates_sha: str,
               baselines_sha: str,
               run: Callable[[], dict]) -> Job:
        """Register a job and schedule ``run`` (a sync callable returning the
        result payload) on the loop. Raises ``JobStoreFull`` past caps --
        ``run`` is never invoked then."""
        job = Job(job_id=uuid.uuid4().hex, status="queued", variant=variant,
                  n_calls=n_calls, rates_sha=rates_sha, baselines_sha=baselines_sha)
        with self._lock:
            self._evict_locked(time.monotonic())
            if self._active_locked() >= self._max_active:
                raise JobStoreFull(
                    f"{self._active_locked()} jobs already queued/running; "
                    f"limit is {self._max_active}")
            self._jobs[job.job_id] = job
        job_task = asyncio.get_running_loop().create_task(self._serve(job, run))
        job_task.add_done_callback(_log_task_crash)
        return job

    async def _serve(self, job: Job, run: Callable[[], dict]) -> None:
        async with self._semaphore:
            with self._lock:
                if job.status == "queued":
                    job.status = "running"
            try:
                result = await asyncio.to_thread(run)
            except Exception as exc:  # noqa: BLE001 -- job errors are data
                with self._lock:
                    job.status = "error"
                    job.error = f"{type(exc).__name__}: {exc}"
            else:
                with self._lock:
                    job.status = "done"
                    job.result = result


def _log_task_crash(task: asyncio.Task) -> None:
    """Last-resort guard: _serve catches everything, so a crash here means a
    bug in status bookkeeping itself -- surface it in logs, never silently."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:  # pragma: no cover - defensive; _serve never raises
        import logging
        logging.getLogger("turnstile_service.jobs").exception(
            "job task crashed", exc_info=exc)


def run_experiment_job(priced_traces: list, variant) -> dict:
    """The worker body: gated variant sweep over pre-priced traces.

    Same functions the CLI path composes (``map_trials`` +
    ``aggregate_experiment``), plus exact Wilson counts from the trials and
    the §8.3 gate verdict. Refuses paid backends before touching anything.
    """
    if not isinstance(get_backend(), MockBackend):
        raise RuntimeError(
            "refusing experiment: process backend is "
            f"{type(get_backend()).__name__}, not MockBackend ($0 only)"
        )
    trials = map_trials(priced_traces, variant)
    result = aggregate_experiment(trials)
    non_excluded = [t for t in trials if t.status != "excluded"]
    counted = [t for t in non_excluded if t.outcome_preserved is not None]
    successes = sum(1 for t in counted if t.outcome_preserved)
    wilson_lo, wilson_hi = wilson_interval(successes, len(counted))
    return {
        "experiment": result.model_dump(mode="json"),
        "passes_gate": passes_gate(result),
        "variant": variant.model_dump(mode="json", exclude_none=True),
        "n_calls": len(priced_traces),
        "outcome_preservation_wilson_ci95": [wilson_lo, wilson_hi],
        "provenance": {
            "backend": "MockBackend",
            "note": MOCK_BACKEND_PROVENANCE,
        },
    }
