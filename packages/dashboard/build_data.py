"""Regenerate packages/dashboard/sample/*.json from the REAL Turnstile pipeline
run over the 23 golden fixtures (fixtures/golden/*.json).

Architecture (W3-B Item 1): this script writes ONLY data. ``index.html`` is
hand-authored and fetches that data over http; the build never regenerates,
embeds, or otherwise touches HTML (an earlier revision rewrote index.html's
embedded fallback blocks and mangled the panel containers -- that path is
gone; test_build_data.py asserts no .html file changes when this runs).

Usage::

    uv run python packages/dashboard/build_data.py
    # then serve: uv run python -m http.server --directory packages/dashboard

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
from pathlib import Path

from turnstile_schema import Baselines, VariantSpec, load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate
from turnstile_detectors import detect
from turnstile_replay import experiment
from turnstile_corpus.distributions import BARGE_IN_RATE
from turnstile_experiments import (
    CONDITIONAL_SAVINGS_LABEL,
    REPRICING_VARIANTS,
    run_repricing_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden"
RATES_PATH = ROOT / "pricing" / "rates.yaml"
BASELINES_PATH = ROOT / "fixtures" / "sample" / "baselines.json"

# The barge-in headline's data source: the harness CLI's own output (real
# Piper synthesis; modeled/swept barge-in rate + position). The dashboard
# never hardcodes harness numbers -- it renders this report, and the build
# refuses to run without it.
BARGEIN_REPORT_PATH = ROOT / "experiments" / "bargein_report.json"

DASHBOARD_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = DASHBOARD_DIR / "sample"

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
    "docs/LIMITATIONS.md for the tiers. Recoverable margin is a PER-DATASET "
    "figure (it depends on the fleet), always deterministic rate arbitrage and "
    "needing no live calls: THIS panel's number is over these 23 golden "
    "fixtures; the reproducible reference is 0.57% over the 250-trace corpus. "
    "A live backend adds only real latency/throughput, not the margin."
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


def _analyze(path: Path, rates, baselines):
    """Run the real pipeline over one fixture: priced trace, verdict, findings."""
    priced, verdict = _priced_and_verdict(path, rates)
    findings = []
    for finding in detect(priced, verdict, baselines):
        data = finding.model_dump(mode="json")
        # VariantSpec sets only the knobs it changes (see contracts.py) --
        # drop the unset ones here so the dashboard's "proposed variant"
        # column shows the one or two keys that matter, not six nulls.
        data["proposed_variant"] = finding.proposed_variant.model_dump(
            mode="json", exclude_none=True
        )
        findings.append(data)
    return priced, verdict, findings


# --------------------------------------------------------------------------- #
# 1. findings.sample.json -- detect() over every fixture, real output          #
# --------------------------------------------------------------------------- #

def build_findings(rates, baselines) -> list[dict]:
    findings: list[dict] = []
    for path in _golden_fixtures():
        _, _, per_call = _analyze(path, rates, baselines)
        findings.extend(per_call)
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
    stage_totals: dict[str, float] = {}

    for path in _golden_fixtures():
        priced, verdict = _priced_and_verdict(path, rates)
        n_conversations += 1
        total_cost_usd += priced.conv_cost
        for stage, cost in priced.stage_costs.items():
            stage_totals[stage] = stage_totals.get(stage, 0.0) + cost
        if verdict.label.value == "RESOLVED":
            resolved_cost_usd += priced.conv_cost
            n_resolved += 1

    cprc_naive = resolved_cost_usd / n_resolved if n_resolved else 0.0
    cprc_loaded = total_cost_usd / n_resolved if n_resolved else 0.0

    # Recoverable Margin % = Sum(proven_savings) / CPRC_loaded (PRD Sec.4.3).
    # proven_savings counts only interventions where replay achieved
    # outcome-preservation >= 0.95 with the bootstrap 95% CI UPPER bound on
    # delta_cost strictly < 0 -- i.e. a proven saving, never a proven cost
    # increase. This is the canonical turnstile_experiments.recoverable_margin
    # gate (_passes_gate); the ingest pipeline converged onto it in Item 5.4 and
    # this was the last divergent copy. Our only replay evidence this wave is the
    # MockBackend mechanism-demo experiment below -- see its own provenance
    # note; this metric inherits that same "mechanism, not measured" caveat.
    proven_savings_total = 0.0
    _ci_lo, ci_hi = experiment_result["delta_cost_ci95"]
    if experiment_result["outcome_preservation_rate"] >= 0.95 and ci_hi < 0.0:
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
        "stage_costs_usd": stage_totals,
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
# 5. bargein.sample.json -- the measured barge-in headline, from the harness   #
#    report (regenerated by run_bargein_harness.py; never recomputed here)     #
# --------------------------------------------------------------------------- #

def build_bargein(report: dict) -> dict:
    """Derive the barge-in headline panel from the harness report dict -- the
    CLI's own output, verbatim. NOTHING here is recomputed or hardcoded:
    every number traces to ``report`` (asserted by test_build_data.py); this
    function only picks the headline point (the cited default barge-in rate,
    ``turnstile_corpus.distributions.BARGE_IN_RATE``), carries the harness's
    provenance string through verbatim, and derives the floor annotation for
    the lead-cap table from the report's own points."""
    by_rate = {p["barge_in_rate"]: p for p in report["points"]}
    if BARGE_IN_RATE not in by_rate:
        raise ValueError(
            f"barge-in report has no point at the cited default rate "
            f"{BARGE_IN_RATE} -- regenerate the report with the default "
            f"BARGE_IN_RATES (run_bargein_harness.py)"
        )
    headline = by_rate[BARGE_IN_RATE]

    leadcap_points = report["lead_cap_sweep"]["points"]
    floor = _flat_run(leadcap_points, "lead_cap_s", "waste_share_of_tts_spend")

    return {
        "label": "D7 barge-in unheard waste — measured on the barge-in harness",
        "n": report["n"],
        "seed": report["seed"],
        "lead_cap_s": report["lead_cap_s"],
        "headline": dict(headline),
        "rate_sweep": report["points"],
        "lead_cap_sweep": report["lead_cap_sweep"],
        "granularity_sweep": report["granularity_sweep"],
        "floor_annotation": floor,
        # The harness's own provenance string, verbatim -- keep it attached.
        "provenance": report["provenance"],
        "report_source": (
            "experiments/bargein_report.json, generated by "
            "packages/experiments/run_bargein_harness.py (real Piper TTS "
            "synthesis; barge-in rate and position modeled and swept). The "
            "dashboard renders this report; it computes no harness number."
        ),
    }


def _flat_run(points: list[dict], key: str, value_key: str) -> dict | None:
    """The lead-cap sweep's measured floor: the longest run of consecutive
    points whose value is identical (to float precision) -- 'waste stops
    falling' is the synthesis-chunk floor the lead_cap sweep exposed. Pure
    read-out of the report's own numbers; None when no flat run of >= 2."""
    best: list[dict] = []
    run: list[dict] = []
    last = None
    for p in points:
        v = p[value_key]
        if last is not None and v == last:
            run.append(p)
        else:
            run = [p]
        last = v
        if len(run) > len(best):
            best = list(run)
    if len(best) < 2:
        return None
    return {
        "from": best[0][key],
        "to": best[-1][key],
        "value": best[0][value_key],
        "note": (
            "waste is flat across these lead caps -- the measured "
            "synthesis-chunk floor (the in-flight chunk is atomic)"
        ),
    }


def load_bargein_report(path: Path = BARGEIN_REPORT_PATH) -> dict:
    """Read the harness report, failing loud (with the exact regeneration
    command) when it is absent -- the dashboard never fabricates it."""
    if not path.exists():
        raise SystemExit(
            f"barge-in report not found at {path} -- generate it first: "
            f"`uv run --group piper python packages/experiments/"
            f"run_bargein_harness.py --n 150 --seed 0`. The dashboard "
            f"renders the harness's own output and never hardcodes it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 6. conditional.sample.json -- the Section-A re-pricing remedies, in their    #
#    OWN clearly-labeled bucket ("detected + quantified, not proven")          #
# --------------------------------------------------------------------------- #

# Which detector each re-pricing remedy answers (documentation for the panel
# row; the mapping mirrors variants.py's registry docstrings).
REPRICING_DETECTOR = {
    "context_window_8": "D2 (context bloat) / D4 (turn inflation)",
    "context_summarize_2000": "D4 (turn inflation)",
    "prefix_caching_on": "D2 (context bloat)",
    "tool_batching_on": "D10 (tool thrash)",
    "escalation_threshold_0_85": "D9 (escalation debt)",
    "retrieval_threshold_0_8": "D3 (redundant retrieval)",
}

CONDITIONAL_PROVENANCE = (
    "DETERMINISTIC CONDITIONAL SAVINGS — " + CONDITIONAL_SAVINGS_LABEL + ". "
    "Deterministic re-pricing over the 23 golden fixtures via "
    "run_repricing_matrix (no backend, no spend); the transform reduces or "
    "re-rates work, so preservation of the outcome is UNMEASURABLE on the "
    "synthetic corpus (H-1). These numbers are NEVER added to the gated "
    "recoverable margin (this fleet's proven number) and must not be presented "
    "as measured or proven savings. Verified in Wave-2 or not at all."
)


def build_conditional_savings(rates, corpus) -> dict:
    """Run the Section-A deterministic re-pricing remedies over the corpus
    (the same 23 golden fixtures every other panel uses) and package the
    conditional bucket. The numbers ARE ``run_repricing_matrix``'s output —
    this function only maps remedy rows to their detectors and carries the
    verbatim label; nothing is recomputed, and nothing here mixes with the
    gated proven savings."""
    results = run_repricing_matrix(corpus, REPRICING_VARIANTS, rates=rates)
    variants = {
        name: {
            "detector": REPRICING_DETECTOR[name],
            "n": r.n,
            "delta_cost_mean": r.delta_cost_mean,
            "delta_cost_ci95": list(r.delta_cost_ci95),
            "savings_usd": -r.delta_cost_mean,
            "savings_usd_ci95": [-r.delta_cost_ci95[1], -r.delta_cost_ci95[0]],
            "label": r.label,
        }
        for name, r in results.items()
    }
    return {
        "label": "Section-A re-pricing remedies — deterministic conditional savings",
        "label_verbatim": CONDITIONAL_SAVINGS_LABEL,
        "variants": variants,
        "total_savings_usd": sum(v["savings_usd"] for v in variants.values()),
        "n_fixtures": len(corpus),
        "_provenance": CONDITIONAL_PROVENANCE,
    }


# --------------------------------------------------------------------------- #
# 7. calls.json + call-<id>.json -- per-call data for ALL calls (W3-B Item 2)#
# --------------------------------------------------------------------------- #

def build_calls(rates, baselines) -> tuple[list[dict], dict[str, dict]]:
    """Per-call index rows + per-call detail payloads for every golden fixture.

    The index row carries what the call list shows (id, scenario, cost,
    verdict, top waste); the detail payload carries what the drill-down
    shows (the full priced trace for the flame graph, the verdict, this
    call's own findings). The dashboard renders these payloads verbatim --
    nothing is recomputed in the browser."""
    index: list[dict] = []
    details: dict[str, dict] = {}
    for path in _golden_fixtures():
        call_id = path.stem
        priced, verdict, findings = _analyze(path, rates, baselines)
        top = max(findings, key=lambda f: f["waste_usd"], default=None)
        index.append(
            {
                "id": call_id,
                "scenario_id": priced.trace.conversation.scenario_id,
                "cost_usd": priced.conv_cost,
                "verdict": verdict.label.value,
                "end_reason": priced.trace.conversation.end_reason.value,
                "n_turns": len(priced.trace.turns),
                "top_waste": (
                    None
                    if top is None
                    else {
                        "class_id": top["class_id"],
                        "waste_usd": top["waste_usd"],
                        "span_id": top["span_id"],
                        "turn_index": top["turn_index"],
                    }
                ),
                "detail": f"call-{call_id}.json",
            }
        )
        data = priced.model_dump(mode="json")
        data["_provenance"] = {
            "fixture": call_id,
            "note": (
                "Per-call priced trace over a golden fixture (same tiers as "
                "the fleet: LLM stage measured from real token counts, "
                "acoustic stages modeled by the fixture generator; verdict "
                "and findings from the real pipeline -- see docs/METHOD.md)."
            ),
        }
        data["verdict"] = verdict.model_dump(mode="json")
        data["findings"] = findings
        details[call_id] = data
    return index, details


# --------------------------------------------------------------------------- #
# 8. manifest.json -- data source declaration + the W3-A Item 5 hook          #
# --------------------------------------------------------------------------- #

# Where the turnstile_ingest report (W3-A Item 5) plugs in. The dashboard
# NEVER depends on it existing: manifest["ingest"]["report_path"] is null
# until the ingest artifact is wired, and index.html renders the golden-fleet
# data with an honest "ingest absent" note. Wired, build_ingest() below copies
# the committed ingest artifact (packages/ingest/data/data.json + its
# call-<id>.json details, filenames unchanged so the dashboard's existing
# per-call router resolves them) into sample/ as sample/ingest.json, and the
# manifest declares status "available" + that report_path. Contract for the
# producer:
INGEST_CONTRACT = {
    # Minimal envelope the dashboard surfaces verbatim (no other keys read).
    "report_envelope": {"label": "str", "n": "int", "note": "str", "provenance": "str"},
    # Full motion: per-call files shaped EXACTLY like this builder's
    # call-<id>.json (keys: trace, span_costs, turn_costs, conv_cost,
    # stage_costs, verdict, findings, _provenance) plus matching
    # sample/calls.json rows (keys: id, scenario_id, cost_usd, verdict,
    # end_reason, n_turns, top_waste, detail). Call ids must be
    # filename-safe and match the dashboard route ([A-Za-z0-9_-]).
    "per_call_files": "sample/call-<id>.json + sample/calls.json rows, same keys as golden",
    "index_row_keys": ["id", "scenario_id", "cost_usd", "verdict", "end_reason",
                       "n_turns", "top_waste", "detail"],
    "detail_keys": ["trace", "span_costs", "turn_costs", "conv_cost",
                    "stage_costs", "verdict", "findings", "_provenance"],
    # Honesty rule (the typical real-log case): calls WITHOUT G2 acoustic
    # fields (chars_synthesized/chars_played) MUST carry no D6/D7/D8
    # findings -- honestly absent, never zero-filled. The dashboard maps
    # class_ids 1-10 and all 7 verdict labels already; nothing new needed.
    "acoustic_rule": "no G2 fields -> no D6/D7/D8 findings (absent, not zero)",
}


# The committed turnstile_ingest output this builder publishes into
# sample/. Filenames are preserved verbatim (ingest call ids never collide
# with golden ids), so the dashboard's existing `sample/call-<id>.json`
# router resolves ingest drill-downs with no new fetch path.
INGEST_DATA_DIR = ROOT / "packages" / "ingest" / "data"
INGEST_SOURCE_FILE = INGEST_DATA_DIR / "data.json"
INGEST_REPORT_FILE = "ingest.json"


def build_ingest(sample_dir: Path = SAMPLE_DIR) -> dict | None:
    """Publish the committed ingest report into the dashboard's sample dir.

    Reads ``packages/ingest/data/data.json`` (NO number is recomputed or
    hardcoded -- the artifact's own fleet/calls/findings/coverage travel
    verbatim) plus every per-call file its index rows point at, and writes
    them to ``sample/ingest.json`` + ``sample/call-<id>.json``. Returns the
    manifest hook (``status``/``report_path``) or None when the artifact is
    absent -- the dashboard then honestly renders golden-only data."""
    if not INGEST_SOURCE_FILE.exists():
        return None
    artifact = json.loads(INGEST_SOURCE_FILE.read_text(encoding="utf-8"))
    # Minimal envelope check (manifest INGEST_CONTRACT): the dashboard reads
    # exactly these keys, so fail loud here rather than ship a half-report.
    for key in ("label", "n", "note", "provenance", "fleet",
                "coverage_summary", "calls", "findings"):
        if key not in artifact:
            raise ValueError(
                f"ingest artifact {INGEST_SOURCE_FILE} lacks {key!r} "
                f"(see manifest ingest.contract) -- regenerate it: "
                f"`uv run python -m turnstile_ingest --sample`"
            )
    for row in artifact["calls"]:
        if set(row) != set(INGEST_CONTRACT["index_row_keys"]):
            raise ValueError(
                f"ingest index row {row.get('id')!r} keys {sorted(row)} != "
                f"dashboard contract {INGEST_CONTRACT['index_row_keys']}"
            )
        detail_src = INGEST_DATA_DIR / row["detail"]
        if not detail_src.exists():
            raise ValueError(
                f"ingest per-call file missing: {detail_src} "
                f"(row {row.get('id')!r}) -- regenerate it: "
                f"`uv run python -m turnstile_ingest --sample`"
            )
        sample_dir.mkdir(parents=True, exist_ok=True)
        (sample_dir / row["detail"]).write_text(
            detail_src.read_text(encoding="utf-8"), encoding="utf-8")
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / INGEST_REPORT_FILE).write_text(
        json.dumps(artifact, indent=2), encoding="utf-8")
    return {"status": "available", "report_path": f"sample/{INGEST_REPORT_FILE}"}


def build_manifest(calls_index: list[dict], ingest: dict | None = None) -> dict:
    hook = {
        "status": "awaiting W3-A Item 5",
        "report_path": None,
        "contract": INGEST_CONTRACT,
    }
    if ingest is not None:
        hook = {**hook, **ingest}
    return {
        "label": "Turnstile dashboard data manifest",
        "source": "golden-fixtures",
        "calls_index": "sample/calls.json",
        "hero": HERO_FIXTURE,
        "n_calls": len(calls_index),
        "ingest": hook,
    }


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
    bargein = build_bargein(load_bargein_report())
    corpus = [price_trace(load_trace(p), rates) for p in _golden_fixtures()]
    conditional = build_conditional_savings(rates, corpus)

    SAMPLE_DIR.mkdir(exist_ok=True)
    (SAMPLE_DIR / "priced_trace.json").write_text(json.dumps(priced_trace, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "fleet.json").write_text(json.dumps(fleet, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "findings.sample.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "experiments.sample.json").write_text(json.dumps(experiments, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "bargein.sample.json").write_text(json.dumps(bargein, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "conditional.sample.json").write_text(json.dumps(conditional, indent=2), encoding="utf-8")

    calls_index, call_details = build_calls(rates, baselines)
    calls_payload = {
        "label": "All calls -- per-call cost, verdict, and top waste",
        "source": "golden-fixtures",
        "n": len(calls_index),
        # The drill-down's default call (also the fleet hero flame graph).
        "hero": HERO_FIXTURE,
        "calls": calls_index,
    }
    (SAMPLE_DIR / "calls.json").write_text(json.dumps(calls_payload, indent=2), encoding="utf-8")
    for call_id, data in call_details.items():
        (SAMPLE_DIR / f"call-{call_id}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    ingest_hook = build_ingest(SAMPLE_DIR)
    manifest = build_manifest(calls_index, ingest_hook)
    (SAMPLE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(f"wrote {SAMPLE_DIR / 'priced_trace.json'}  (hero fixture: {HERO_FIXTURE})")
    print(f"wrote {SAMPLE_DIR / 'fleet.json'}  cprc_naive={fleet['cprc_naive']:.6f}  cprc_loaded={fleet['cprc_loaded']:.6f}")
    print(f"wrote {SAMPLE_DIR / 'findings.sample.json'}  n_findings={len(findings)}")
    print(f"wrote {SAMPLE_DIR / 'experiments.sample.json'}  n_trials={experiments[0]['n']}")
    headline = bargein["headline"]
    print(f"wrote {SAMPLE_DIR / 'bargein.sample.json'}  headline: "
          f"{headline['waste_share_of_tts_spend']:.2%} of TTS spend unheard at "
          f"barge-in rate {headline['barge_in_rate']} (harness n={bargein['n']})")
    print(f"wrote {SAMPLE_DIR / 'conditional.sample.json'}  "
          f"total conditional savings ${conditional['total_savings_usd']:.4f} "
          f"({CONDITIONAL_SAVINGS_LABEL}) -- NOT the gated margin")
    print(f"wrote {SAMPLE_DIR / 'calls.json'}  n_calls={len(calls_index)} "
          f"+ {len(call_details)} per-call detail files")
    print(f"wrote {SAMPLE_DIR / 'manifest.json'}  source=golden-fixtures "
          f"ingest={manifest['ingest']['status']}")
    if ingest_hook is not None:
        report = json.loads((SAMPLE_DIR / INGEST_REPORT_FILE).read_text(encoding="utf-8"))
        print(f"wrote {SAMPLE_DIR / INGEST_REPORT_FILE}  n={report['n']} "
              f"margin={report['fleet']['recoverable_margin_pct']:.2f}% "
              f"over these {report['n']} ingest calls "
              f"+ {len(report['calls'])} per-call detail files")


if __name__ == "__main__":
    main()
