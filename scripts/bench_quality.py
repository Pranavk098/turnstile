"""Day-4 Part D latency benchmark: the deterministic quality slice vs its budget.

Measures, on this machine (numbers are machine-relative -- transcript only,
never a committed doc):

1. ``evaluate_quality`` over the 23 golden traces (N iterations each;
   median + p95 per call, plus the worst-call p95 that the gate reads).
2. The full ``_run_priced`` path WITH vs WITHOUT the quality call (the
   without-shape stubs only ``pipeline.evaluate_quality`` -- identical code
   path otherwise), isolating the added ms/call.

GATE: quality-slice p95 < 20 ms/call (day-PRD latency budget, tightened).

Run from the repo root::

    uv run python scripts/bench_quality.py [--iterations 200]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover - runner convenience
    sys.path.insert(0, str(ROOT))

from turnstile_ingest.adapter import DEFAULT_RATES_PATH
from turnstile_ingest import pipeline as _pipeline
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, _run_priced
from turnstile_pricing import price_trace
from turnstile_quality import evaluate_quality
from turnstile_schema import Baselines, load_rates, load_trace
from turnstile_verdict import adjudicate

GATE_P95_MS = 20.0


def _p95_ms(samples: list[float]) -> float:
    if len(samples) == 1:
        return float(samples[0])
    try:
        return float(statistics.quantiles(samples, n=100)[94])
    except statistics.StatisticsError:
        ordered = sorted(samples)
        return float(ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95)))])


def _time_call(fn, n: int) -> tuple[float, float]:
    fn()  # warm-up (import/page costs must not bill the slice)
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return float(statistics.median(samples)), _p95_ms(samples)


def _golden_priced_verdicts():
    import json

    rates = load_rates(DEFAULT_RATES_PATH)
    baselines = Baselines.model_validate(
        json.loads(Path(DEFAULT_BASELINES_PATH).read_text(encoding="utf-8")))
    goldens = sorted((ROOT / "fixtures" / "golden").glob("*.json"),
                     key=lambda p: p.name)
    goldens = [p for p in goldens if not p.name.startswith("_")]
    assert len(goldens) == 23, f"expected 23 golden traces, saw {len(goldens)}"
    pairs = []
    for path in goldens:
        priced = price_trace(load_trace(path), rates)
        verdict = adjudicate(priced)
        pairs.append((path.stem, priced, verdict))
    return pairs, rates, baselines


def _doc_example_call() -> dict:
    import copy
    import json

    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    call = copy.deepcopy(json.loads(fence))
    call["id"] = "call-bench-quality-001"
    return call


class _NoQuality:
    """Stand-in for a QualityReport with only the method _run_priced reads."""

    def model_dump(self, mode: str = "json") -> dict:
        return {"overall": {"label": "pass", "tier": "measured"},
                "dimensions": [], "evidence": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=200)
    args = ap.parse_args()
    n = args.iterations

    pairs, rates, baselines = _golden_priced_verdicts()

    print(f"evaluate_quality over {len(pairs)} golden traces x {n} iterations:")
    worst_p95, worst_name = 0.0, ""
    medians = []
    for stem, priced, verdict in pairs:
        med, p95 = _time_call(lambda: evaluate_quality(priced, verdict), n)
        medians.append(med)
        worst_p95, worst_name = (p95, stem) if p95 > worst_p95 else (worst_p95, worst_name)
        print(f"  {stem:22s} median {med:7.3f} ms/call   p95 {p95:7.3f} ms/call")
    mean_median = sum(medians) / len(medians)
    print(f"  {'MEAN-median':22s} median {mean_median:7.3f} ms/call")
    print(f"  {'WORST-p95':22s} ({worst_name}) p95 {worst_p95:7.3f} ms/call")

    gate_ok = worst_p95 < GATE_P95_MS
    print(f"GATE quality-slice p95 < {GATE_P95_MS:.0f} ms/call: "
          f"{'PASS' if gate_ok else 'FAIL'} ({worst_p95:.3f} ms)")

    call = _doc_example_call()
    med_with, p95_with = _time_call(
        lambda: _run_priced(call, rates, baselines), n)
    real_eval = _pipeline.evaluate_quality
    _pipeline.evaluate_quality = lambda p, v: _NoQuality()  # noqa: E731
    try:
        med_without, p95_without = _time_call(
            lambda: _run_priced(call, rates, baselines), n)
    finally:
        _pipeline.evaluate_quality = real_eval
    print(f"_run_priced WITH quality:    median {med_with:7.3f} ms/call   "
          f"p95 {p95_with:7.3f} ms/call")
    print(f"_run_priced WITHOUT quality: median {med_without:7.3f} ms/call   "
          f"p95 {p95_without:7.3f} ms/call")
    print(f"isolated quality add:        median {med_with - med_without:7.3f} ms/call   "
          f"p95 {p95_with - p95_without:7.3f} ms/call")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
