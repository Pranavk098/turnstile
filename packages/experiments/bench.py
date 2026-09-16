"""Day-3 Track A benchmark harness (unoptimized-tree baseline recorder).

Measures the existing engine entry points WITHOUT changing them:

* ``per-trace``: ``generate_corpus(n, seed)`` -> ``price_trace`` ->
  ``adjudicate`` -> ``detect`` per trace (timed with ``time.perf_counter``).
  Reports median/p95 microseconds per trace plus the total.
* ``matrix``: ``run_matrix_checkpointed_detailed`` over ``VARIANTS`` on the
  free ``MockBackend`` only, serial (``max_workers=1``). Reports wall seconds
  plus per-variant means.

$0 rule: this harness MUST refuse any paid run -- it exits 1 when ``--paid``
is passed OR when ``TURNSTILE_ALLOW_PAID`` is set in the environment, printing
"$0 only". There is no paid path here by design.

Honesty rule (charter sect 1.4): every surfaced number carries its methodology
(n, hardware, seed). This module never prints a bare comparative claim.

Usage::

    uv run python packages/experiments/bench.py --n 30 --seed 0 --mode per-trace
    uv run python packages/experiments/bench.py --n 250 --seed 0 --mode matrix \\
        --out experiments/baseline-day3.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from turnstile_corpus import generate_corpus
from turnstile_detectors import detect
from turnstile_experiments import VARIANTS, compute_baselines
from turnstile_pricing import price_trace
from turnstile_replay import MockBackend
from turnstile_experiments import run_matrix_checkpointed_detailed
from turnstile_schema import load_rates
from turnstile_verdict import adjudicate

ROOT = Path(__file__).resolve().parents[2]
RATES_PATH = ROOT / "pricing" / "rates.yaml"


def _git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        sha = proc.stdout.strip()
        return sha if proc.returncode == 0 and sha else "unknown"
    except Exception:
        return "unknown"


def methodology(n: int, seed: int, repeat: int) -> dict:
    """Methodology header (charter sect 1.4): every output JSON carries this."""
    return {
        "n": n,
        "seed": seed,
        "repeat": repeat,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "backend": "MockBackend",
    }


def _percentile_us(sorted_samples: list[float], q: float) -> float:
    """Nearest-rank percentile over ASCENDING sorted samples (stdlib only)."""
    if not sorted_samples:
        return 0.0
    idx = math.ceil(q * len(sorted_samples)) - 1
    idx = max(0, min(idx, len(sorted_samples) - 1))
    return sorted_samples[idx]


def run_per_trace(n: int, seed: int, repeat: int) -> dict:
    """Time price->adjudicate->detect per trace; median/p95 us + total."""
    rates = load_rates(RATES_PATH)
    raw_traces = generate_corpus(n, seed)
    # Setup (untimed): price once to calibrate per-intent baselines, so the
    # timed loop measures the steady-state pipeline, not calibration.
    setup_priced = [price_trace(t, rates) for t in raw_traces]
    baselines = compute_baselines(setup_priced)

    samples_us: list[float] = []
    for _ in range(repeat):
        for trace in raw_traces:
            start = time.perf_counter()
            priced = price_trace(trace, rates)
            verdict = adjudicate(priced)
            detect(priced, verdict, baselines)
            end = time.perf_counter()
            samples_us.append((end - start) * 1e6)

    ordered = sorted(samples_us)
    total_us = sum(samples_us)
    return {
        "n_traces": n,
        "repeat": repeat,
        "n_samples": len(samples_us),
        "per_trace_us": {
            "median": statistics.median(ordered) if ordered else 0.0,
            "p95": _percentile_us(ordered, 0.95),
            "mean": statistics.fmean(ordered) if ordered else 0.0,
            "min": ordered[0] if ordered else 0.0,
            "max": ordered[-1] if ordered else 0.0,
        },
        "total_us": total_us,
        "total_sec": total_us / 1e6,
    }


def run_matrix(n: int, seed: int, repeat: int) -> dict:
    """Serial MockBackend matrix; wall sec per repeat + per-variant means."""
    rates = load_rates(RATES_PATH)
    raw_traces = generate_corpus(n, seed)
    corpus = [price_trace(t, rates) for t in raw_traces]

    walls: list[float] = []
    per_variant: dict[str, dict] = {}
    for _ in range(repeat):
        # Fresh checkpoint per repeat: reusing one would serve cached trials
        # and misreport a resumed wall as a full-run wall.
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "bench-checkpoint.jsonl"
            start = time.perf_counter()
            matrix, _real_usage = run_matrix_checkpointed_detailed(
                corpus, VARIANTS, checkpoint,
                backend=MockBackend(), max_workers=1,
            )
            end = time.perf_counter()
            walls.append(end - start)
            per_variant = {
                name: {
                    "delta_cost_mean": result.delta_cost_mean,
                    "n": result.n,
                }
                for name, result in matrix.items()
            }

    ordered = sorted(walls)
    return {
        "n_traces": n,
        "repeat": repeat,
        "wall_sec": {
            "per_repeat": walls,
            "mean": statistics.fmean(walls) if walls else 0.0,
            "median": statistics.median(ordered) if ordered else 0.0,
            "min": ordered[0] if ordered else 0.0,
            "max": ordered[-1] if ordered else 0.0,
        },
        "per_variant": per_variant,
        "variants": sorted(VARIANTS.keys()),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Day-3 Track A benchmark harness (MockBackend only, $0).")
    parser.add_argument("--n", type=int, default=30,
                        help="corpus size (default: 30; gate uses 250)")
    parser.add_argument("--seed", type=int, default=0,
                        help="corpus RNG seed, deterministic (default: 0)")
    parser.add_argument("--repeat", type=int, default=5,
                        help="measurement repeats (default: 5)")
    parser.add_argument("--mode", type=str, default="per-trace",
                        choices=["per-trace", "matrix"],
                        help="per-trace pipeline or serial experiment matrix")
    parser.add_argument("--out", type=str, default=None,
                        help="output JSON path (writes methodology + results)")
    parser.add_argument("--paid", action="store_true",
                        help="REFUSED: bench.py is $0/MockBackend only")
    args = parser.parse_args(argv)

    if args.paid or os.environ.get("TURNSTILE_ALLOW_PAID") == "1":
        print("$0 only: bench.py runs on MockBackend and refuses paid runs "
              "(--paid passed or TURNSTILE_ALLOW_PAID is set). Unset "
              "TURNSTILE_ALLOW_PAID and re-run without --paid.")
        sys.exit(1)

    meta = methodology(args.n, args.seed, args.repeat)
    if args.mode == "per-trace":
        results = run_per_trace(args.n, args.seed, args.repeat)
    else:
        results = run_matrix(args.n, args.seed, args.repeat)

    payload = {"methodology": meta, "mode": args.mode, "results": results}

    # Honesty: every printed number rides with n/hardware/seed.
    print(f"bench mode={args.mode} n={args.n} seed={args.seed} "
          f"repeat={args.repeat} backend=MockBackend")
    print(f"hardware: {meta['platform']} cpus={meta['cpu_count']} "
          f"python={meta['python']} git_sha={meta['git_sha']}")
    if args.mode == "per-trace":
        pt = results["per_trace_us"]
        print(f"per-trace us (n={args.n}, seed={args.seed}): "
              f"median={pt['median']:.1f} p95={pt['p95']:.1f} "
              f"mean={pt['mean']:.1f} min={pt['min']:.1f} max={pt['max']:.1f}")
        print(f"total: {results['total_sec']:.3f}s over "
              f"{results['n_samples']} samples")
    else:
        wall = results["wall_sec"]
        print(f"matrix wall sec (n={args.n}, seed={args.seed}, "
              f"serial max_workers=1): mean={wall['mean']:.3f} "
              f"median={wall['median']:.3f} min={wall['min']:.3f} "
              f"max={wall['max']:.3f}")
        for name, block in results["per_variant"].items():
            print(f"variant {name}: delta_cost_mean={block['delta_cost_mean']:.6f} "
                  f"n={block['n']}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote baseline to {out_path}")


if __name__ == "__main__":
    main()
