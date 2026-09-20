"""Day-3 follow-on: CI perf-regression smoke (same-run ratios, never absolute us).

The committed baselines (``experiments/baseline-day3*.json``) are machine-
specific historical records for PERF.md -- CI runners differ, so this gate
never compares against them. Every assertion is a SAME-RUN ratio measured on
the runner itself, so CPU speed cancels out:

* ``test_parallel_ratio_and_identity``: serial median wall vs parallel median
  wall over the same corpus in the same run. Day-3's quantitative gate is
  >=2x at n=250 on the PERF.md hardware; this CI smoke asserts >=1.5x at
  n=80 with median-of-3 on both sides, so a slow/shared runner cannot flake
  the green gate, while a real parallelism regression (e.g. the ordered
  reduce removed, or workers silently serialized) still fails. Aggregates
  MUST hash identically (the actual correctness gate, nearly free here).
* ``test_per_trace_within_reference_band``: per-trace median normalized by a
  same-run reference workload (deterministic dict/json/sha256 loop). At
  Day-3 sign-off the ratio measured 26.4 (n=30/seed=0, Win11/20-CPU,
  py3.13.12); the gate is 80 (~3x headroom). The class of regression this
  catches: the detector optional-dependency re-probing bug pushed per-trace
  p95 to ~1250us, a ratio of ~375 -- it fails loudly, machine-independent.

$0: MockBackend only. Runtime target: <30s on a small runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from pathlib import Path

import pytest

from turnstile_corpus import generate_corpus
from turnstile_detectors import detect
from turnstile_experiments import (
    VARIANTS,
    compute_baselines,
    run_matrix_checkpointed_detailed,
)
from turnstile_pricing import price_trace
from turnstile_replay import MockBackend
from turnstile_schema import load_rates
from turnstile_verdict import adjudicate

ROOT = Path(__file__).resolve().parents[1]
RATES_PATH = ROOT / "pricing" / "rates.yaml"

#: CI smoke thresholds (see module docstring for the derivation + evidence).
PARALLEL_RATIO_MIN = 1.5
PER_TRACE_RATIO_MAX = 80.0


def _hash_matrix(matrix) -> str:
    """Stable sha256 over a matrix result dict (self-contained copy of the
    Track A helper: pydantic models dumped to plain JSON first)."""
    plain: dict[str, object] = {}
    for name in sorted(matrix.keys()):
        value = matrix[name]
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        plain[name] = json.loads(json.dumps(value, sort_keys=True))
    return hashlib.sha256(
        json.dumps(plain, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _matrix_wall_and_hash(corpus, workers: int, checkpoint: Path) -> tuple[float, str]:
    start = time.perf_counter()
    matrix, _ = run_matrix_checkpointed_detailed(
        corpus, VARIANTS, checkpoint, backend=MockBackend(), max_workers=workers)
    return time.perf_counter() - start, _hash_matrix(matrix)


def test_parallel_ratio_and_identity(tmp_path):
    """Parallel matrix SHALL be >=1.5x serial (same-run medians) with
    byte-identical aggregate hashes."""
    workers = min(8, os.cpu_count() or 1)
    if workers < 2:
        pytest.skip("parallel ratio is meaningless on a single CPU")
    rates = load_rates(RATES_PATH)
    corpus = [price_trace(t, rates) for t in generate_corpus(80, 0)]

    serial_walls, parallel_walls = [], []
    serial_hash = parallel_hash = ""
    for rep in range(3):
        wall, serial_hash = _matrix_wall_and_hash(
            corpus, 1, tmp_path / f"serial-{rep}.jsonl")
        serial_walls.append(wall)
        wall, parallel_hash = _matrix_wall_and_hash(
            corpus, workers, tmp_path / f"parallel-{rep}.jsonl")
        parallel_walls.append(wall)

    assert serial_hash == parallel_hash, (
        "parallel aggregates diverged from serial -- correctness defect, "
        "not a perf miss")
    ratio = statistics.median(serial_walls) / statistics.median(parallel_walls)
    assert ratio >= PARALLEL_RATIO_MIN, (
        f"parallel speedup {ratio:.2f}x < {PARALLEL_RATIO_MIN}x CI smoke "
        f"(serial median {statistics.median(serial_walls):.3f}s, parallel "
        f"median {statistics.median(parallel_walls):.3f}s, n=80, "
        f"workers={workers}); Day-3 gate remains >=2x at n=250 per PERF.md")


def _reference_op_seconds(iterations: int = 2000) -> float:
    """Median seconds/iter of a fixed dict+json+sha256 loop (CPU-speed probe)."""
    payload = {"a": list(range(20)), "b": "x" * 40, "c": {"d": 1.5}}
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        for i in range(iterations):
            hashlib.sha256(
                json.dumps({**payload, "i": i}, sort_keys=True).encode()
            ).hexdigest()
        samples.append((time.perf_counter() - start) / iterations)
    return statistics.median(samples)


def test_per_trace_within_reference_band():
    """Per-trace price->adjudicate->detect median, normalized by the same-run
    reference op, SHALL stay under 80 (26.4 measured at Day-3 sign-off)."""
    rates = load_rates(RATES_PATH)
    raw = generate_corpus(30, 0)
    baselines = compute_baselines([price_trace(t, rates) for t in raw])
    samples = []
    for _ in range(3):
        for trace in raw:
            start = time.perf_counter()
            priced = price_trace(trace, rates)
            verdict = adjudicate(priced)
            detect(priced, verdict, baselines)
            samples.append(time.perf_counter() - start)
    per_trace = statistics.median(samples)
    ratio = per_trace / _reference_op_seconds()
    assert ratio <= PER_TRACE_RATIO_MAX, (
        f"per-trace/reference ratio {ratio:.1f} > {PER_TRACE_RATIO_MAX} "
        f"(per-trace median {per_trace * 1e6:.1f}us); measured 26.4 at "
        "Day-3 sign-off -- a hot-path regression landed")
