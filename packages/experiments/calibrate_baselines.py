"""Calibrate ``fixtures/sample/baselines.json`` from the synthetic corpus
(GAP-07, batch doc Section B1).

Replaces the hand-authored per-intent rows with ``compute_baselines`` output
over ``generate_corpus`` at the stated (n, seed), and writes a sibling
provenance file recording exactly what produced them. Rerun after any
corpus-distribution change:

    uv run python packages/experiments/calibrate_baselines.py

Calibration parameters: **n=250, seed=0** -- the canonical corpus reference
(the same parameters behind docs/METHOD.md's 0.57% headline run), no
seed selection. An earlier revision shopped for a seed that kept the golden-
fixture false-positive gate green, because corpus-calibrated D4 fired on
fixture 09 (a 13-turn billing_dispute; corpus billing_dispute p75 ~10). That
was resolved at the source, not by seed choice: fixture 09 genuinely IS
turn-inflated (its own narrative is "predictable at turn 3, ran 9 more"), so
its manifest now declares ``target_detector: "4,9"`` and D4 firing on it is
the calibrated world being correct, not a false positive. Seed 0 is therefore
sweep-safe and the calibration uses the canonical reference parameters.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_schema import load_rates

from turnstile_experiments import compute_baselines

ROOT = Path(__file__).resolve().parents[2]
RATES_PATH = ROOT / "pricing" / "rates.yaml"
OUT_PATH = ROOT / "fixtures" / "sample" / "baselines.json"
PROVENANCE_PATH = ROOT / "fixtures" / "sample" / "baselines.provenance.json"

N = 250
SEED = 0


def main() -> None:
    rates = load_rates(RATES_PATH)
    corpus = [price_trace(t, rates) for t in generate_corpus(N, SEED)]
    baselines = compute_baselines(corpus)

    sample_counts: dict[str, int] = {}
    for pt in corpus:
        sid = pt.trace.conversation.scenario_id
        sample_counts[sid] = sample_counts.get(sid, 0) + 1

    OUT_PATH.write_text(
        json.dumps({"per_intent": {
            sid: {
                "p50_turns": v.p50_turns,
                "p75_turns": v.p75_turns,
                "mean_cost_per_turn": v.mean_cost_per_turn,
            }
            for sid, v in baselines.per_intent.items()
        }}, indent=2) + "\n",
        encoding="utf-8",
    )
    PROVENANCE_PATH.write_text(
        json.dumps({
            "n": N,
            "seed": SEED,
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "generator": "turnstile_corpus.generate_corpus(n, seed)",
            "pricing": "turnstile_pricing.price_trace vs pricing/rates.yaml",
            "calibration": "turnstile_experiments.compute_baselines",
            "per_intent_sample_counts": dict(sorted(sample_counts.items())),
            "selection_note": (
                "Canonical corpus reference parameters: n=250, seed=0 (the same "
                "parameters behind docs/METHOD.md's 0.57% headline run) -- no "
                "seed selection. Corpus-calibrated D4 fires on fixture 09 (a "
                "13-turn billing_dispute; corpus p75 ~10), which is CORRECT: "
                "fixture 09 is genuinely turn-inflated and its manifest now "
                "declares target_detector '4,9'. See calibrate_baselines.py's "
                "docstring."
            ),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_PATH}")
    print(f"wrote {PROVENANCE_PATH}")
    for sid, v in baselines.per_intent.items():
        print(f"  {sid:24s} p50={v.p50_turns:5.1f} p75={v.p75_turns:5.1f} "
              f"mean_cost_per_turn={v.mean_cost_per_turn:.6f} (n={sample_counts.get(sid, 0)})")


if __name__ == "__main__":
    main()
