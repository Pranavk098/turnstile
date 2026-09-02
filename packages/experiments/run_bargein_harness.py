"""CLI: run the measured barge-in waste harness (native Windows, real Piper,
NO WSL2/telephony/ASR/LLM) and write the D7 number with its provenance.

Spends NOTHING: Piper is local synthesis; the only "calls" are harness
invocations of the built price->adjudicate->detect instrument.

Usage (from the repository root)::

    uv run --extra piper python packages/experiments/run_bargein_harness.py \\
        --n 150 --seed 0 --out experiments/bargein_report.json

Requires the piper extra and a voice model (env TURNSTILE_PIPER_MODEL, or
~/en_US-lessac-medium.onnx). The output JSON embeds the provenance string
stating exactly what is measured vs modeled -- keep it attached to the number.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from turnstile_experiments import run_bargein_report

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Measured barge-in waste (D7) -- native Piper harness."
    )
    parser.add_argument("--n", type=int, default=150, help="calls per sweep point")
    parser.add_argument("--seed", type=int, default=0, help="RNG seed (deterministic)")
    parser.add_argument(
        "--rates", type=float, nargs="*", default=None,
        help="barge-in rate sweep values (default: the cited band 0.05..0.30)",
    )
    parser.add_argument(
        "--lead-cap-s", type=float, default=2.0,
        help="streaming buffer policy: max generated-but-unheard audio seconds",
    )
    parser.add_argument(
        "--out", type=str, default="experiments/bargein_report.json",
        help="output JSON path",
    )
    args = parser.parse_args(argv)

    try:
        report = run_bargein_report(
            rates_values=args.rates, n=args.n, seed=args.seed,
            lead_cap_s=args.lead_cap_s,
        )
    except RuntimeError as exc:
        print(f"Cannot start the harness: {exc}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"provenance: {report['provenance']}\n")
    print(f"{'rate':>6} {'calls':>6} {'barge-ins':>10} {'D7 $':>10} "
          f"{'$/call':>10} {'%TTS spend':>11} {'gen-rate':>9}")
    for p in report["points"]:
        print(
            f"{p['barge_in_rate']:>6.2f} {p['n_calls']:>6} "
            f"{p['barge_in_calls']:>10} {p['d7_waste_usd_total']:>10.4f} "
            f"{p['d7_waste_usd_mean_per_call']:>10.5f} "
            f"{p['waste_share_of_tts_spend']:>10.2%} "
            f"{p['mean_gen_rate_realtime_x']:>8.1f}x"
        )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
