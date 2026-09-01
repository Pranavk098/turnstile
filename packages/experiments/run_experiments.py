"""CLI: generate a corpus, compute per-intent baselines from it, run the
6-variant experiment matrix, compute the errata-corrected recoverable margin
(PRD Sec.4.3), and write results to JSON.

Default path spends NOTHING: MockBackend only (``packages/replay``'s free,
deterministic Wave-1 backend). ``--paid`` selects the real
``turnstile_experiments.OpenAIBackend`` -- but it REFUSES to run unless
``TURNSTILE_ALLOW_PAID=1`` is set in the environment: it prints the cost
estimate and exits instead, exactly as docs/CORPUS.md's "gated, owner-
approved paid run" requires. Even with the flag set, a paid run normally
requires an interactive ``yes`` confirmation after the estimate is shown;
``--yes`` (H-2, for scripted runs) skips that prompt -- the env gate still
applies -- so ``--paid --yes`` can run without a TTY.

M-1: both output paths (``--out`` and ``--checkpoint``) are probe-written
(parent created, file opened for append) BEFORE any backend is constructed,
so an unwritable path aborts the run before a cent is spent -- never losing
a paid run at the end.

Usage::

    uv run python packages/experiments/run_experiments.py --n 30 --seed 0
    uv run python packages/experiments/run_experiments.py --n 250 --paid
        # refuses unless TURNSTILE_ALLOW_PAID=1 is set
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_schema import load_rates

from turnstile_experiments import (
    VARIANTS,
    build_manifest,
    compute_baselines,
    estimate_cost,
    recoverable_margin,
    run_matrix_checkpointed_detailed,
)
from turnstile_replay import DELTA_COST_REAL_USAGE_LABEL

ROOT = Path(__file__).resolve().parents[2]
RATES_PATH = ROOT / "pricing" / "rates.yaml"


def _ensure_writable(path: Path, flag: str) -> None:
    """M-1: create the parent directory and probe-write `path` (open for
    append -- never truncates an existing results file), so an unwritable
    output path aborts the run BEFORE any backend construction / spend."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        print(f"--{flag} path is not writable: {path} ({exc}). Aborting before any spend.")
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Turnstile experiment matrix.")
    parser.add_argument("--n", type=int, default=30, help="corpus size (default: 30)")
    parser.add_argument("--seed", type=int, default=0, help="corpus RNG seed (deterministic)")
    parser.add_argument(
        "--annual-calls", type=int, default=1_000_000,
        help="assumed annual call volume for the annualized savings projection",
    )
    parser.add_argument("--out", type=str, default="experiments/results.json", help="output JSON path")
    parser.add_argument(
        "--checkpoint", type=str, default=None,
        help="trace-level checkpoint JSONL path (default: <out>.checkpoint.jsonl). "
             "A resumed run reuses completed trials and never re-spends on them.",
    )
    parser.add_argument(
        "--paid", action="store_true",
        help="use the real OpenAIBackend instead of the free MockBackend "
             "(REFUSES unless TURNSTILE_ALLOW_PAID=1 is set)",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="skip the interactive paid-run confirmation (for scripted runs "
             "without a TTY); the TURNSTILE_ALLOW_PAID=1 env gate still applies",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="thread workers for the per-trace replay map (Change B); "
             "default 1 = sequential. Aggregates are identical regardless",
    )
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    checkpoint_path = (
        Path(args.checkpoint) if args.checkpoint
        else out_path.with_suffix(".checkpoint.jsonl")
    )
    # M-1: probe-write BOTH output paths before anything expensive (and
    # before any backend construction), so an unwritable path can never
    # abort a paid run at the end and lose it.
    _ensure_writable(out_path, "out")
    _ensure_writable(checkpoint_path, "checkpoint")

    rates = load_rates(RATES_PATH)
    traces = generate_corpus(args.n, args.seed)
    corpus = [price_trace(t, rates) for t in traces]
    print(f"corpus: {len(corpus)} traces (seed={args.seed})")

    baselines = compute_baselines(corpus)
    estimate = estimate_cost(corpus, VARIANTS, rates=rates)

    backend = None
    if args.paid:
        if os.environ.get("TURNSTILE_ALLOW_PAID") != "1":
            print(
                "\n--paid requested but TURNSTILE_ALLOW_PAID=1 is not set in the "
                "environment. Refusing to spend money. Set TURNSTILE_ALLOW_PAID=1 "
                "and OPENAI_API_KEY, and re-run, to proceed with the estimate above."
            )
            sys.exit(1)
        if args.yes:
            # H-2: scripted runs have no TTY -- input() would raise EOFError.
            # --yes skips the prompt; the env gate above still applies.
            print("--yes given: skipping interactive paid-run confirmation.")
        else:
            confirm = input(
                f"\nAbout to spend an estimated ${estimate['total_estimated_usd']:.4f} "
                "on real OpenAI API calls. Type 'yes' to continue: "
            )
            if confirm.strip().lower() != "yes":
                print("Not confirmed -- aborting paid run.")
                sys.exit(1)
        from turnstile_experiments import OpenAIBackend
        backend = OpenAIBackend()

    backend_name = "OpenAIBackend" if backend is not None else "MockBackend"
    manifest = build_manifest(
        seed=args.seed, n=len(corpus), backend_name=backend_name,
        variants=VARIANTS, corpus=corpus, rates_path=RATES_PATH, root=ROOT,
    )

    matrix, real_usage = run_matrix_checkpointed_detailed(
        corpus, VARIANTS, checkpoint_path, backend=backend, max_workers=args.workers)

    total_cost = sum(pt.conv_cost for pt in corpus)
    margin = recoverable_margin(matrix, total_cost, args.annual_calls)

    results = {
        "n_corpus": len(corpus),
        "seed": args.seed,
        "backend": backend_name,
        "manifest": manifest,
        "baselines": baselines.model_dump(),
        "matrix": {name: result.model_dump() for name, result in matrix.items()},
        # CR-B companion figure, NOT gated: priced on the REAL replayed usage,
        # so its scale includes the render-size mismatch between real rendered
        # prompts and the corpus's synthetic input_tokens. PRD Sec.8.3's gate
        # applies to matrix[*].delta_cost only.
        "delta_cost_real_usage_mean_usd": {
            "label": DELTA_COST_REAL_USAGE_LABEL,
            "per_variant": real_usage,
        },
        "recoverable_margin": margin,
        "cost_estimate": estimate,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote results to {out_path}")
    print(f"recoverable margin: {margin['recoverable_margin_pct']:.2f}% "
          f"[{margin['recoverable_margin_pct_ci95'][0]:.2f}, {margin['recoverable_margin_pct_ci95'][1]:.2f}]")


if __name__ == "__main__":
    main()
