"""``turnstile_ingest`` CLI: ingest JSON -> full pipeline -> data artifact.

Usage::

    uv run python -m turnstile_ingest [--in calls.json | --sample] [--out DIR]

Reads one call object, a {"calls": [...]} file, or the bundled sample;
runs price -> adjudicate -> detect with the honest acoustic-absence envelope;
writes ``<out>/data.json`` (the artifact W3-B renders: fleet + findings +
per-call reports + coverage, same fleet/findings shapes the dashboard
consumes); prints the headline (recoverable margin + which detectors had
data).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from turnstile_schema import Baselines, load_rates
from turnstile_ingest.adapter import DEFAULT_RATES_PATH
from turnstile_ingest.model import classify_file
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, run_calls

_PACKAGE_DIR = Path(__file__).resolve().parents[2]
SAMPLE_PATH = _PACKAGE_DIR / "sample" / "calls.json"
DEFAULT_OUT_DIR = _PACKAGE_DIR / "data"


def load_input_file(path: Path) -> tuple[list, bool]:
    """Return (call objects, sample_flag) for --in/--sample input."""
    obj = json.loads(path.read_text(encoding="utf-8"))
    kind = classify_file(obj)
    if kind == "call":
        return [obj], bool(obj.get("sample", False)) if isinstance(obj, dict) else False
    if kind == "callset":
        calls = obj["calls"] if isinstance(obj, dict) else obj
        sample = bool(obj.get("sample", False)) if isinstance(obj, dict) else False
        if not isinstance(calls, list) or not calls:
            raise SystemExit(f"{path}: 'calls' must be a non-empty list")
        return calls, sample
    raise SystemExit(
        f"{path}: expected one call object (with 'id') or "
        f"a callset (with 'calls') -- see docs/INGEST.md"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--in", dest="input", type=Path, help="ingest JSON file")
    source.add_argument("--sample", action="store_true", help="run the bundled sample")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--rates", type=Path, default=DEFAULT_RATES_PATH)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.input is None and not args.sample:
        args.sample = True
    input_path = args.input if args.input is not None else SAMPLE_PATH
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")
    calls, sample = load_input_file(input_path)

    rates = load_rates(args.rates)
    baselines = Baselines.model_validate(json.loads(args.baselines.read_text(encoding="utf-8")))
    artifact = run_calls(
        calls, rates, baselines,
        label="ingested sample (7 calls)" if sample else f"ingested {input_path.name}",
        sample=sample,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "data.json"
    out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    fleet = artifact["fleet"]
    summary = artifact["coverage_summary"]["calls_with_data_per_class"]
    n = artifact["coverage_summary"]["n_calls"]
    full = [c for c in range(1, 11) if summary.get(str(c), 0) == n]
    partial = [(c, summary.get(str(c), 0)) for c in range(1, 11) if summary.get(str(c), 0) != n]
    print(f"ingested {n} call(s) from {input_path} -> {out_path}")
    print(f"total cost ${fleet['total_cost_usd']:.4f} over {n} calls, "
          f"{fleet['n_resolved']} resolved; "
          f"recoverable margin {fleet['recoverable_margin_pct']:.2f}% "
          "(§8.3-gated D1 reroute, MockBackend mechanism)")
    print(f"detectors with data on all {n} calls: "
          + (", ".join(f"D{c}" for c in full) or "none"))
    for class_id, v in partial:
        print(f"D{class_id}: data on {v}/{n} calls, ABSENT on {n - v} (no data for this input)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
