"""CLI: run the D7 (barge-in) and D8 (silence-tax) sensitivity sweeps and
write ``sweeps.json``. No OpenAI/network calls -- pure corpus regeneration +
price -> adjudicate -> detect pipeline re-runs (see
``turnstile_experiments.sweeps`` for the sweep logic and docs/DEMO.md's
"Detector 8 as a hypothesis, not a claim" for why this exists: D7 and D8 are
Tier-2 detectors whose dollar magnitude is a function of one named generator
parameter, not a claimed fact).

Usage::

    uv run python packages/experiments/sweeps.py --n 80 --seed 7
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from turnstile_schema import load_rates

from turnstile_experiments import run_sweeps
from turnstile_experiments.sweeps import DEFAULT_N, DEFAULT_SEED

ROOT = Path(__file__).resolve().parents[2]
RATES_PATH = ROOT / "pricing" / "rates.yaml"


def _print_table(title: str, param_label: str, points: list[dict]) -> None:
    print(f"\n{title}")
    header = f"  {param_label:>14} | {'findings':>8} | {'waste_usd':>10} | {'share':>7}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for p in points:
        print(
            f"  {p['param_value']:>14} | {p['detector_findings']:>8} | "
            f"{p['detector_waste_usd']:>10.4f} | {p['detector_share_of_findings']:>6.1%}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the D7/D8 sensitivity sweeps (packages/experiments/sweeps.py)."
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N, help=f"corpus size per sweep point (default: {DEFAULT_N})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"corpus RNG seed, fixed across a sweep (default: {DEFAULT_SEED})")
    parser.add_argument("--out", type=str, default="experiments/sweeps.json", help="output JSON path")
    args = parser.parse_args(argv)

    rates = load_rates(RATES_PATH)
    print(f"running D7/D8 sensitivity sweeps (n={args.n}, seed={args.seed}, no OpenAI/network calls)")

    results = run_sweeps(rates, n=args.n, seed=args.seed)

    _print_table(
        "D7 barge-in sweep (BARGE_IN_RATE)", "barge_in_rate", results["d7_barge_in_sweep"]["points"]
    )
    _print_table(
        "D8 silence sweep (INTER_TURN_GAP_MEDIAN_MS)", "median_ms", results["d8_silence_sweep"]["points"]
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote sweeps to {out_path}")


if __name__ == "__main__":
    main()
