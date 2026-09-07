"""Re-analysis entry: the intent-preservation oracle over REAL forks (Wave-2).

Reads an existing paid-matrix result JSON (``--result``; no new paid calls,
no network) and runs ``turnstile_verdict.fork_oracle.preserved_under_divergence``
over its divergent exemplars, judging each fork against the trace's
deterministically regenerated ground-truth intent -- deliberately NEVER by
re-adjudicating the fork through pinned downstream tools.

Forked labels come from the result JSON's ``divergent_records`` block
(Wave-2 exp-hardening Item 1: fresh runs self-document their forks, so no
sidecar is needed); ``--sidecar`` (``{trace_id: label}``) remains as a legacy
override for runs that predated fork-persistence. A fork with neither is
``unrecorded`` and can only be reported as undecidable-by-data.

HARD SEPARATION: the output is a MODELED figure
(``preservation_under_divergence_modeled = preserved / decidable``) under its
own key and tier label. It is NEVER folded into the measured
identity-preservation number (0.985 at paid n=250/seed 8), and forks that are
registry-undecidable are reported as ``None`` and listed -- never guessed.

Usage::

    uv run python -m turnstile_experiments.preservation_divergence \
        --result experiments/matrix-paid-n250-s8.json [--sidecar labels.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_replay.replay import _earliest_applicable_turn, _llm_spans_from
from turnstile_schema import VariantSpec, load_rates
from turnstile_verdict.fork_oracle import Decision, preserved_under_divergence

ROOT = Path(__file__).resolve().parents[4]
RATES_PATH = ROOT / "pricing" / "rates.yaml"

TIER_LABEL = (
    "MODELED (ground-truth intent oracle, turnstile_verdict.fork_oracle) -- "
    "separate from the measured identity-preservation figure; never folded "
    "into it. The real measured number requires open-loop execution of the "
    "divergent path (deferred, the honest ceiling)."
)


def _variant_spec(name: str, matrix_block: dict) -> VariantSpec:
    """Rebuild the variant's VariantSpec for pivot selection. Canonical names
    come from turnstile_experiments.VARIANTS; the paid runs' single-variant
    matrix also resolves by the model_routing_<model> name convention."""
    from turnstile_experiments import VARIANTS

    if name in VARIANTS:
        return VARIANTS[name]
    if name.startswith("model_routing_"):
        return VariantSpec(model_routing={"route": name[len("model_routing_"):]})
    raise ValueError(
        f"cannot rebuild VariantSpec for variant {name!r}; pass a canonical "
        f"name from turnstile_experiments.VARIANTS"
    )


def _pivot_decision(trace, variant: VariantSpec):
    """The pivot span (first replayed decision) -- the span the gate judged.
    Single-source helpers from turnstile_replay, same selection replay uses."""
    from_turn = _earliest_applicable_turn(trace, variant)
    spans = _llm_spans_from(trace.trace, from_turn)
    if not spans:
        raise ValueError("fork trace has no replayable llm span")
    return spans[0][1]


def _classification(verdict: bool | None) -> str:
    if verdict is None:
        return "undecidable"
    return "preserved" if verdict else "not_preserved"


def analyze_forks(
    result_json_path: str | Path,
    sidecar_path: str | Path | None = None,
    variant: str | None = None,
) -> dict:
    """Run the intent oracle over the result JSON's divergent exemplars.

    Forked labels come from the result JSON's ``divergent_records`` block
    (Wave-2 exp-hardening Item 1: fresh paid runs self-document their forks)
    with an optional ``--sidecar`` JSON as a legacy override (sidecar wins on
    conflict). A fork with neither is ``unrecorded`` (undecidable-by-data).

    Returns a report dict whose tier label states the MODELED separation;
    ``preservation_under_divergence_modeled`` is ``preserved / decidable``
    over RECORDED forks only (None when nothing is decidable), and unrecorded
    / undecidable forks are counted and listed, never guessed.
    """
    result = json.loads(Path(result_json_path).read_text(encoding="utf-8"))
    matrix = result["matrix"]
    if variant is None:
        assert len(matrix) == 1, "pass --variant for a multi-variant result"
        variant = next(iter(matrix))
    variant_spec = _variant_spec(variant, matrix[variant])
    exemplars: list[str] = matrix[variant].get("divergent_exemplars", [])

    rates = load_rates(RATES_PATH)
    corpus = {
        priced.trace.conversation.conversation_id: priced
        for priced in (
            price_trace(t, rates) for t in generate_corpus(result["n_corpus"], result["seed"])
        )
    }
    # Item 1: fresh result JSONs carry their own fork labels; the sidecar is
    # a legacy override for runs that predated fork-persistence.
    forked_labels: dict[str, str | None] = {}
    forked_texts: dict[str, str | None] = {}
    forked_reasons: dict[str, str | None] = {}
    for rec in matrix[variant].get("divergent_records", []) or []:
        tid = rec.get("trace_id")
        if tid is None:
            continue
        forked_labels[tid] = rec.get("forked_label")
        forked_texts[tid] = rec.get("forked_text")
        forked_reasons[tid] = rec.get("finish_reason")
    if sidecar_path is not None:
        sidecar_labels = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
        forked_labels.update(sidecar_labels)

    rows = []
    for trace_id in sorted(exemplars):
        priced = corpus[trace_id]
        pivot = _pivot_decision(priced, variant_spec)
        intent = priced.trace.conversation.scenario_id
        forked_label = forked_labels.get(trace_id)
        if forked_label is None:
            verdict = None
            classification = "unrecorded"
        else:
            verdict = preserved_under_divergence(
                intent,
                Decision(kind=pivot.decision_kind, label=pivot.decision_chosen),
                Decision(kind=pivot.decision_kind, label=forked_label),
            )
            classification = _classification(verdict)
        rows.append({
            "trace_id": trace_id,
            "intent": intent,
            "pivot_kind": pivot.decision_kind.value,
            "original_label": pivot.decision_chosen,
            "forked_label": forked_label,
            "forked_text": forked_texts.get(trace_id),
            "finish_reason": forked_reasons.get(trace_id),
            "verdict": verdict,
            "classification": classification,
        })

    n_unrecorded = sum(1 for r in rows if r["classification"] == "unrecorded")
    recorded = [r for r in rows if r["classification"] != "unrecorded"]
    n_preserved = sum(1 for r in recorded if r["verdict"] is True)
    n_not_preserved = sum(1 for r in recorded if r["verdict"] is False)
    n_undecidable = sum(1 for r in recorded if r["verdict"] is None)
    n_decidable = n_preserved + n_not_preserved
    return {
        "tier": TIER_LABEL,
        "result_json": str(result_json_path),
        "variant": variant,
        "n_forks": len(rows),
        "n_unrecorded": n_unrecorded,
        "n_decidable": n_decidable,
        "n_preserved": n_preserved,
        "n_not_preserved": n_not_preserved,
        "n_undecidable": n_undecidable,
        "preservation_under_divergence_modeled": (
            n_preserved / n_decidable if n_decidable else None
        ),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Intent-oracle re-analysis over the recorded forks (free; no paid calls)."
    )
    parser.add_argument("--result", required=True, help="paid-matrix result JSON path")
    parser.add_argument("--sidecar", default=None, help="forked-labels sidecar JSON ({trace_id: label})")
    parser.add_argument("--variant", default=None, help="matrix variant name (default: the only one)")
    args = parser.parse_args(argv)
    print(json.dumps(
        analyze_forks(args.result, sidecar_path=args.sidecar, variant=args.variant),
        indent=2, default=str,
    ))


if __name__ == "__main__":
    main()
