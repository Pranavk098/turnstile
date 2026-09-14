"""``turnstile_ingest`` CLI: ingest JSON -> full pipeline -> data artifact.

Usage::

    uv run python -m turnstile_ingest [--in calls.json | --sample] [--out DIR]
    uv run python -m turnstile_ingest --provider vapi --in vapi-export.json [--out DIR]

Reads one call object, a {"calls": [...]} file, or the bundled sample;
runs price -> adjudicate -> detect with the honest acoustic-absence envelope;
writes ``<out>/data.json`` (the artifact the dashboard renders: fleet + findings +
per-call reports + coverage, same fleet/findings shapes the dashboard
consumes); prints the headline (recoverable margin + which detectors had
data).

``--provider vapi`` first maps a Vapi call-export payload (one call, a list,
or a ``calls``/``results``/``data`` wrapper) through
``providers.vapi.from_vapi_export``, then runs the SAME pipeline unchanged.
Inferred ``decision_kind`` labels ride as provenance and never feed the D1
headline (see ``providers.vapi`` and docs/INGEST.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from turnstile_schema import Baselines, load_rates
from turnstile_ingest.adapter import DEFAULT_RATES_PATH, IngestError
from turnstile_ingest.model import classify_file
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, run_calls
from turnstile_ingest.providers import vapi as vapi_provider

_PACKAGE_DIR = Path(__file__).resolve().parents[2]
SAMPLE_PATH = _PACKAGE_DIR / "sample" / "calls.json"
VAPI_SAMPLE_PATH = _PACKAGE_DIR / "sample" / "vapi-export.sample.json"
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
    parser.add_argument("--provider", choices=("turnstile", "vapi"), default="turnstile",
                        help="input format: native IngestCall JSON (default) or a Vapi call export")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--rates", type=Path, default=DEFAULT_RATES_PATH)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.input is None and not args.sample:
        args.sample = True
    if args.provider == "vapi":
        input_path = args.input if args.input is not None else VAPI_SAMPLE_PATH
    else:
        input_path = args.input if args.input is not None else SAMPLE_PATH
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")

    rates = load_rates(args.rates)
    baselines = Baselines.model_validate(json.loads(args.baselines.read_text(encoding="utf-8")))

    provider_records: dict | None = None
    if args.provider == "vapi":
        try:
            raw = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{input_path}: invalid JSON -- {exc}") from exc
        sample_flag = bool(raw.get("sample", False)) if isinstance(raw, dict) else False
        try:
            adapted = vapi_provider.from_vapi_export(raw)
        except IngestError as exc:
            raise SystemExit(f"{input_path}: {exc}") from exc
        raw_items = raw if isinstance(raw, list) else (
            raw.get("calls", raw.get("results", raw.get("data", [raw])))
            if isinstance(raw, dict) else [raw]
        )
        calls = list(adapted)
        provider_records = {
            call.id: vapi_provider.provider_info(raw_obj, call, sample=sample_flag)
            for raw_obj, call in zip(raw_items, adapted)
        }
        label = (f"vapi export sample ({input_path.name})" if sample_flag
                 else f"vapi export {input_path.name}")
        sample = sample_flag
    else:
        calls, sample = load_input_file(input_path)
        label = "ingested sample (7 calls)" if sample else f"ingested {input_path.name}"

    artifact, details = run_calls(
        calls, rates, baselines,
        label=label,
        sample=sample,
        provider=provider_records,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "data.json"
    out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    for filename, detail in details.items():
        (args.out / filename).write_text(json.dumps(detail, indent=2), encoding="utf-8")

    fleet = artifact["fleet"]
    summary = artifact["coverage_summary"]["calls_with_data_per_class"]
    n = artifact["coverage_summary"]["n_calls"]
    n_excluded = artifact["coverage_summary"].get("margin_excluded", 0)
    full = [c for c in range(1, 11) if summary.get(str(c), 0) == n]
    partial = [(c, summary.get(str(c), 0)) for c in range(1, 11) if summary.get(str(c), 0) != n]
    print(f"ingested {n} call(s) from {input_path} -> {out_path} + {len(details)} per-call files")
    if args.provider == "vapi":
        print("source: Vapi export" + (" (synthetic schema-conformant example)" if sample else "")
              + "; decision_kind inferred on all adapted turns (D1 excluded from measured waste)")
    print(f"total cost ${fleet['total_cost_usd']:.4f} over {n} calls, "
          f"{fleet['n_resolved']} resolved; "
          f"recoverable margin {fleet['recoverable_margin_pct']:.2f}% "
          "(§8.3-gated D1 reroute, MockBackend mechanism)")
    if n_excluded:
        print(f"margin over {n - n_excluded}/{n} calls -- {n_excluded} "
              "provider-adapted call(s) excluded (inferred decision_kind)")
    print(f"detectors with data on all {n} calls: "
          + (", ".join(f"D{c}" for c in full) or "none"))
    for class_id, v in partial:
        print(f"D{class_id}: data on {v}/{n} calls, ABSENT on {n - v} (no data for this input)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
