"""Regenerate packages/dashboard/sample/*.json from the REAL Turnstile pipeline
run over the 23 golden fixtures (fixtures/golden/*.json), and keep index.html's
embedded ``<script type="application/json">`` fallback copies in sync with
those files (both copies are written from the same in-memory objects in this
script, so they cannot drift).

Usage::

    uv run python packages/dashboard/build_data.py

Honest two-tier labeling (see docs/DEMO.md, docs/CORPUS.md): this generator
runs the real pricing/verdict/detectors/replay pipeline against the 23 golden
fixtures. The LLM-cost layer is a real computation over real token counts
(Tier 1). The ASR/TTS/telephony cost layer runs the identical pricing formula
but over the fixture generator's MODELED acoustics, not a live audio pipeline
(Tier 2 -- mechanism, not a measured magnitude). The replay/experiment panel
uses the Wave-1 MockBackend (no live LLM call) -- it demonstrates the replay
MECHANISM, not a measured production outcome-preservation rate. Every JSON
file this script writes carries an explicit provenance note saying so; do not
strip those notes when regenerating.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from turnstile_schema import Baselines, VariantSpec, load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate
from turnstile_detectors import detect
from turnstile_replay import experiment

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
RATES_PATH = ROOT / "pricing" / "rates.yaml"
BASELINES_PATH = ROOT / "fixtures" / "sample" / "baselines.json"

DASHBOARD_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = DASHBOARD_DIR / "sample"
INDEX_HTML = DASHBOARD_DIR / "index.html"

# 09_escalation_debt has the richest stage decomposition (asr+llm+tts+telephony
# all present) and is the fixture the D9 tier-1 "predictable at turn 3, ran 9
# more turns" story is about -- the natural hero trace for the flame graph.
HERO_FIXTURE = "09_escalation_debt"

# D1 (over-model)'s cheapest-tier reroute, expressed as a replay variant: any
# fixture with a "route" decision_kind is a candidate (turnstile_replay's
# _earliest_applicable_turn finds the earliest such turn; fixtures with no
# "route" decision get status="excluded" and do not count toward n -- so
# passing every fixture in is equivalent to "the fixtures where it applies"
# without hand-picking a subset, in keeping with docs/CORPUS.md's "generate/
# detect first, don't tune to fit a narrative" rule).
OVER_MODEL_VARIANT = VariantSpec(model_routing={"route": "gpt-5-nano"})

PROVENANCE_NOTE = (
    "Fixture-scale output (n=23 golden fixtures). LLM-layer measured (real "
    "token counts x pricing/rates.yaml); acoustic layer (ASR/TTS/telephony) "
    "modeled by the fixture generator, not a live audio pipeline; replay via "
    "the Wave-1 MockBackend (mechanism, not measured). See docs/METHOD.md and "
    "docs/LIMITATIONS.md for the tiers. The Tier-1 headline is the DETERMINISTIC "
    "rate-arbitrage recoverable margin (0.57%; needs no live calls); a live "
    "backend adds only real latency/throughput."
)

EXPERIMENT_PROVENANCE = (
    "mechanism demo -- MockBackend, not measured. MockBackend's safe-reroute "
    "path returns the identical output_text/decision_chosen for a cheaper "
    "same-family model, so outcome_preservation_rate=1.0 here is a property "
    "of the mock (cheaper==same outcome by construction), not an observed "
    "production result. Outcome-preservation is NOT measurable on a synthetic "
    "corpus (canned inputs/outputs, pinned tools -> structural); it needs "
    "authored utterances then real traffic (Wave-2). delta_cost is deterministic "
    "rate arbitrage, needing no live backend (docs/LIMITATIONS.md)."
)


def _golden_fixtures() -> list[Path]:
    return sorted(GOLDEN.glob("*.json"))


def _priced_and_verdict(path: Path, rates):
    trace = load_trace(path)
    priced = price_trace(trace, rates)
    verdict = adjudicate(priced)
    return priced, verdict


# --------------------------------------------------------------------------- #
# 1. findings.sample.json -- detect() over every fixture, real output          #
# --------------------------------------------------------------------------- #

def build_findings(rates, baselines) -> list[dict]:
    findings: list[dict] = []
    for path in _golden_fixtures():
        priced, verdict = _priced_and_verdict(path, rates)
        for finding in detect(priced, verdict, baselines):
            data = finding.model_dump(mode="json")
            # VariantSpec sets only the knobs it changes (see contracts.py) --
            # drop the unset ones here so the dashboard's "proposed variant"
            # column shows the one or two keys that matter, not six nulls.
            data["proposed_variant"] = finding.proposed_variant.model_dump(
                mode="json", exclude_none=True
            )
            findings.append(data)
    return findings


# --------------------------------------------------------------------------- #
# 2. priced_trace.json -- one representative fixture for the hero flame graph #
# --------------------------------------------------------------------------- #

def build_priced_trace(rates) -> dict:
    path = GOLDEN / f"{HERO_FIXTURE}.json"
    trace = load_trace(path)
    priced = price_trace(trace, rates)
    data = priced.model_dump(mode="json")
    data["_provenance"] = {
        "fixture": HERO_FIXTURE,
        "stage_tier": {
            "llm": "tier1_measured",
            "asr": "tier2_modeled_acoustics",
            "tts": "tier2_modeled_acoustics",
            "telephony": "tier2_modeled_acoustics",
        },
        "note": (
            "LLM stage cost is computed from this fixture's real token counts "
            "(Tier 1, measured). ASR/TTS/telephony stage costs are computed "
            "with the same pricing formula but over the fixture generator's "
            "modeled acoustics, not a live audio pipeline (Tier 2, mechanism "
            "-- not a measured magnitude; see docs/DEMO.md)."
        ),
    }
    return data


# --------------------------------------------------------------------------- #
# 3. fleet.json -- REAL headline metrics over the 23 fixtures (PRD Sec.4.3)    #
# --------------------------------------------------------------------------- #

def build_fleet(rates, baselines, experiment_result: dict) -> dict:
    total_cost_usd = 0.0
    resolved_cost_usd = 0.0
    n_resolved = 0
    n_conversations = 0

    for path in _golden_fixtures():
        priced, verdict = _priced_and_verdict(path, rates)
        n_conversations += 1
        total_cost_usd += priced.conv_cost
        if verdict.label.value == "RESOLVED":
            resolved_cost_usd += priced.conv_cost
            n_resolved += 1

    cprc_naive = resolved_cost_usd / n_resolved if n_resolved else 0.0
    cprc_loaded = total_cost_usd / n_resolved if n_resolved else 0.0

    # Recoverable Margin % = Sum(proven_savings) / CPRC_loaded (PRD Sec.4.3).
    # proven_savings counts only interventions where replay achieved
    # outcome-preservation >= 0.95 with the bootstrap CI confirming a real
    # (non-zero-crossing) effect. Our only replay evidence this wave is the
    # MockBackend mechanism-demo experiment below -- see its own provenance
    # note; this metric inherits that same "mechanism, not measured" caveat.
    proven_savings_total = 0.0
    ci_lo, ci_hi = experiment_result["delta_cost_ci95"]
    ci_confirms_effect = (ci_lo < 0 and ci_hi < 0) or (ci_lo > 0 and ci_hi > 0)
    if experiment_result["outcome_preservation_rate"] >= 0.95 and ci_confirms_effect:
        proven_savings_total = -experiment_result["delta_cost_mean"] * experiment_result["n"]
    recoverable_margin_pct = (
        (proven_savings_total / total_cost_usd * 100.0) if total_cost_usd else 0.0
    )

    return {
        "label": "Wave-1 real fleet (23 golden fixtures)",
        "note": (
            "Real computed aggregate over the 23 golden fixtures -- not a "
            "production fleet sample. CPRC_naive/CPRC_loaded per PRD Sec.4.3."
        ),
        "n_conversations": n_conversations,
        "n_resolved": n_resolved,
        "total_cost_usd": total_cost_usd,
        "resolved_cost_usd": resolved_cost_usd,
        "cprc_loaded": cprc_loaded,
        "cprc_naive": cprc_naive,
        "recoverable_margin_pct": recoverable_margin_pct,
        "_provenance": {"n": n_conversations, "note": PROVENANCE_NOTE},
    }


# --------------------------------------------------------------------------- #
# 4. experiments.sample.json -- real replay() via MockBackend (mechanism demo) #
# --------------------------------------------------------------------------- #

def build_experiments(rates) -> list[dict]:
    priced_traces = [price_trace(load_trace(p), rates) for p in _golden_fixtures()]
    result = experiment(priced_traces, OVER_MODEL_VARIANT)
    data = result.model_dump(mode="json")
    data_with_label = {
        "label": "D1 over-model reroute: route -> gpt-5-nano",
        "variant": OVER_MODEL_VARIANT.model_dump(mode="json", exclude_none=True),
        **data,
        "_provenance": EXPERIMENT_PROVENANCE,
    }
    return [data_with_label]


# --------------------------------------------------------------------------- #
# index.html embedded-fallback sync                                           #
# --------------------------------------------------------------------------- #

_EMBED_IDS = {
    "data-priced": "priced_trace.json",
    "data-fleet": "fleet.json",
    "data-findings": "findings.sample.json",
    "data-experiments": "experiments.sample.json",
}


def sync_embedded_json(payloads: dict[str, object]) -> None:
    """Rewrite each <script type="application/json" id="...">...</script>
    block in index.html so the embedded file:// fallback matches the freshly
    written sample/*.json files exactly (same in-memory objects, same
    json.dumps call) -- keeps the two copies from drifting apart."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    for elem_id, payload in payloads.items():
        compact = json.dumps(payload, separators=(",", ":"))
        pattern = re.compile(
            r'(<script type="application/json" id="' + re.escape(elem_id) + r'">\n)'
            r'.*?'
            r'(\n</script>)',
            re.DOTALL,
        )
        new_html, count = pattern.subn(lambda m: m.group(1) + compact + m.group(2), html)
        if count != 1:
            raise RuntimeError(f"expected exactly one embedded block for {elem_id!r}, found {count}")
        html = new_html
    INDEX_HTML.write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def main() -> None:
    rates = load_rates(RATES_PATH)
    baselines = Baselines.model_validate(json.loads(BASELINES_PATH.read_text(encoding="utf-8")))

    experiments = build_experiments(rates)
    fleet = build_fleet(rates, baselines, experiments[0])
    findings = build_findings(rates, baselines)
    priced_trace = build_priced_trace(rates)

    SAMPLE_DIR.mkdir(exist_ok=True)
    (SAMPLE_DIR / "priced_trace.json").write_text(json.dumps(priced_trace, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "fleet.json").write_text(json.dumps(fleet, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "findings.sample.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "experiments.sample.json").write_text(json.dumps(experiments, indent=2), encoding="utf-8")

    sync_embedded_json({
        "data-priced": priced_trace,
        "data-fleet": fleet,
        "data-findings": findings,
        "data-experiments": experiments,
    })

    print(f"wrote {SAMPLE_DIR / 'priced_trace.json'}  (hero fixture: {HERO_FIXTURE})")
    print(f"wrote {SAMPLE_DIR / 'fleet.json'}  cprc_naive={fleet['cprc_naive']:.6f}  cprc_loaded={fleet['cprc_loaded']:.6f}")
    print(f"wrote {SAMPLE_DIR / 'findings.sample.json'}  n_findings={len(findings)}")
    print(f"wrote {SAMPLE_DIR / 'experiments.sample.json'}  n_trials={experiments[0]['n']}")
    print(f"synced embedded fallback JSON in {INDEX_HTML}")


if __name__ == "__main__":
    main()
