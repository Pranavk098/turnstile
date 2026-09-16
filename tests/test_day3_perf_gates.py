"""Day-3 Track A perf gates: golden byte-stability + serial-matrix hash helper.

* ``test_golden_bytes_stable``: ``run_calls`` on ``example_call.json`` plus
  the price->adjudicate->detect pipeline over 5 corpus traces (seed 0) is run
  twice; the canonical JSON bytes (``sort_keys``, compact separators) MUST be
  equal. Any engine change that moves an output byte fails here by design.
* ``test_parallel_parity_placeholder``: runs the SERIAL matrix
  (``run_matrix_checkpointed_detailed``, ``MockBackend``, ``max_workers=1``)
  twice and hashes the result dict. No parallel path is implemented here --
  ``hash_matrix()`` is the helper Track C will reuse for the serial-vs-parallel
  aggregate-equality gate.

$0: MockBackend only; no paid backend, no network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from turnstile_corpus import generate_corpus
from turnstile_detectors import detect
from turnstile_experiments import (
    VARIANTS,
    compute_baselines,
    run_matrix_checkpointed_detailed,
)
from turnstile_ingest.adapter import DEFAULT_RATES_PATH
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, run_calls
from turnstile_pricing import price_trace
from turnstile_replay import MockBackend
from turnstile_schema import Baselines, load_rates
from turnstile_verdict import adjudicate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CALL = ROOT / "packages" / "service" / "src" / "turnstile_service" / "example_call.json"


def canonical_bytes(obj) -> bytes:
    """Canonical JSON bytes: sorted keys, compact separators, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_matrix(matrix) -> str:
    """Stable sha256 over a matrix result dict (Track C reuse).

    Accepts ``{name: ExperimentResult}`` or ``{name: dict}``; pydantic models
    are dumped to plain JSON first so serial and parallel aggregates hash
    identically when their contents are equal.
    """
    plain: dict[str, object] = {}
    for name in sorted(matrix.keys()):
        value = matrix[name]
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        plain[name] = json.loads(json.dumps(value, sort_keys=True))
    return hashlib.sha256(canonical_bytes(plain)).hexdigest()


def _rates_and_baselines():
    rates = load_rates(DEFAULT_RATES_PATH)
    baselines = Baselines.model_validate(
        json.loads(Path(DEFAULT_BASELINES_PATH).read_text(encoding="utf-8")))
    return rates, baselines


def _golden_payload() -> dict:
    """run_calls(example_call.json) + 5 corpus traces (seed 0) as one payload.

    Corpus traces are schema ``Trace`` objects (not ingest calls), so they go
    through the same price->adjudicate->detect stages ``bench.py --mode
    per-trace`` times; the ingest example goes through ``run_calls``. Both
    halves are JSON-round-tripped so the bytes compared are wire bytes.
    """
    rates, ingest_baselines = _rates_and_baselines()
    example = json.loads(EXAMPLE_CALL.read_text(encoding="utf-8"))
    artifact, details = run_calls([example], rates, ingest_baselines,
                                  label="day3-golden", sample=False)

    raw = generate_corpus(5, 0)
    priced = [price_trace(t, rates) for t in raw]
    corpus_baselines = compute_baselines(priced)
    traces = []
    for pt in priced:
        verdict = adjudicate(pt)
        findings = detect(pt, verdict, corpus_baselines)
        traces.append({
            "conv_cost": pt.conv_cost,
            "verdict": verdict.model_dump(mode="json"),
            "findings": [f.model_dump(mode="json") for f in findings],
        })

    return {
        "artifact": json.loads(json.dumps(artifact, sort_keys=True)),
        "details": json.loads(json.dumps(details, sort_keys=True)),
        "corpus": json.loads(json.dumps(traces, sort_keys=True)),
    }


def test_golden_bytes_stable():
    first = canonical_bytes(_golden_payload())
    second = canonical_bytes(_golden_payload())
    assert first == second


def test_parallel_parity_placeholder(tmp_path):
    """Serial-only hash: the same serial matrix run twice hashes identically.

    Track C reuses ``hash_matrix()`` to prove parallel aggregates equal serial
    byte-for-byte. This test intentionally does NOT implement parallel.
    """
    rates = load_rates(DEFAULT_RATES_PATH)
    corpus = [price_trace(t, rates) for t in generate_corpus(10, 0)]

    matrix_a, _ = run_matrix_checkpointed_detailed(
        corpus, VARIANTS, tmp_path / "a.jsonl",
        backend=MockBackend(), max_workers=1)
    matrix_b, _ = run_matrix_checkpointed_detailed(
        corpus, VARIANTS, tmp_path / "b.jsonl",
        backend=MockBackend(), max_workers=1)

    digest_a = hash_matrix(matrix_a)
    digest_b = hash_matrix(matrix_b)
    assert digest_a == digest_b
    assert len(digest_a) == 64  # sha256 hex
    assert set(matrix_a.keys()) == set(VARIANTS.keys())
