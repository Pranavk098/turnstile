"""Full pipeline over ingested calls: price -> adjudicate -> detect -> report.

``detect()`` itself is untouched (Item 2: the existing pipeline runs
unchanged). What this module adds is the HONEST coverage envelope (Item 3):

* D7 (barge-in) needs tts/playback char pairs; D6 (dead tokens) needs tts
  text spans; D8 (silence tax) needs the complete span union INCLUDING
  tts/playback intervals (without them, agent speech time misreads as
  silence and D8 over-reports -- docs/GATES.md G1's second-order
  consequence). When the log lacks the G2 acoustic fields the adapter emits
  no (or partial) acoustic spans, so findings for classes {6, 7, 8} on such
  calls are EXCLUDED from the report and the classes are labeled ABSENT with
  the reason -- never zero, never faked.
* D8 additionally needs the telephony leg (``detect`` already returns []
  without one); missing telephony is likewise reported ABSENT, not zero.
* D1-D5, D9, D10 run on the real telemetry (LLM tokens, tools, verdict,
  turn counts) and are labeled PRESENT.

How absence differs from zero, per detector (investigated, not assumed):

* D7 with no tts/playback pairs returns [] -- IDENTICAL to "measured zero
  waste". The coverage envelope is the only thing distinguishing them.
* D8 with no telephony returns [] (explicit guard); with telephony but no
  acoustic spans it returns numbers that are WRONG (inflated gaps), hence
  exclusion rather than pass-through.
* D6 with no tts spans FIRES on every compose turn (unvoiced output reads
  as dead tokens) -- passing that through would fabricate waste, hence
  exclusion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from turnstile_schema import Baselines, PricedTrace, VariantSpec
from turnstile_detectors import detect
from turnstile_pricing import price_trace
from turnstile_replay import experiment
from turnstile_verdict import adjudicate
from turnstile_ingest.adapter import load, parse_call
from turnstile_ingest.model import IngestCall

_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_BASELINES_PATH = _REPO_ROOT / "fixtures" / "sample" / "baselines.json"

ACOUSTIC_CLASSES = (6, 7, 8)
ALWAYS_TELEMETRY_CLASSES = (1, 2, 3, 4, 5, 9, 10)

NO_ACOUSTIC_REASON = (
    "no data for this input: the log carries no G2 acoustic fields "
    "(tts.chars_synthesized/chars_played), so this class cannot be measured"
)
NO_TELEPHONY_REASON = (
    "no data for this input: the call carries no telephony leg, "
    "so silence cannot be priced"
)

# The D1 reroute the dashboard's own build_data.py uses for the gated
# recoverable-margin headline -- same variant, same §8.3 gate, so the ingest
# fleet number means the same thing as the dashboard's.
OVER_MODEL_VARIANT = VariantSpec(model_routing={"route": "gpt-5-nano"})


def describe_coverage(call: IngestCall) -> dict[int, dict[str, str]]:
    """Per-detector data coverage for one validated call.

    Returns ``{class_id: {"status": "present"|"absent", "reason": ...}}``.
    Call-level and conservative: ANY tts turn missing either acoustic field
    marks 6/7/8 absent for the whole call (partial acoustic spans would give
    D7 half-pairs and D8 a holey union).
    """
    tts_turns = [t.tts for t in call.turns if t.tts is not None]
    acoustic_complete = bool(tts_turns) and all(t.acoustic_complete() for t in tts_turns)
    telephony_present = call.telephony is not None

    coverage: dict[int, dict[str, str]] = {}
    for class_id in ALWAYS_TELEMETRY_CLASSES:
        coverage[class_id] = {"status": "present", "reason": "real telemetry in this input"}
    acoustic_status = "present" if acoustic_complete else "absent"
    acoustic_reason = "tts/playback spans with G2 char counts" if acoustic_complete else NO_ACOUSTIC_REASON
    for class_id in (6, 7):
        coverage[class_id] = {"status": acoustic_status, "reason": acoustic_reason}
    if acoustic_complete and telephony_present:
        coverage[8] = {"status": "present", "reason": "telephony leg + complete span union"}
    elif not telephony_present:
        coverage[8] = {"status": "absent", "reason": NO_TELEPHONY_REASON}
    else:
        coverage[8] = {"status": "absent", "reason": NO_ACOUSTIC_REASON}
    return coverage


def _run_priced(
    obj: dict[str, Any] | IngestCall,
    rates,
    baselines: Baselines,
) -> tuple[IngestCall, PricedTrace, dict[str, Any], list[dict[str, Any]]]:
    """Validate + price + adjudicate + detect one call, applying the
    coverage envelope. Returns (call, priced, verdict-dump, finding-dumps)."""
    call = parse_call(obj)
    trace = load(call, rates=rates)
    priced = price_trace(trace, rates)
    verdict = adjudicate(priced)
    coverage = describe_coverage(call)
    raw = detect(priced, verdict, baselines)
    findings = [f for f in raw if coverage[f.class_id]["status"] == "present"]
    return call, priced, verdict, coverage, findings, raw


def run_call(
    obj: dict[str, Any] | IngestCall,
    rates,
    baselines: Baselines,
) -> dict[str, Any]:
    """Price/adjudicate/detect one ingest call; return the JSON-ready report.

    Raises ``IngestError`` on malformed input (from ``load``).
    """
    call, priced, verdict, coverage, findings, raw = _run_priced(obj, rates, baselines)
    dropped = sorted({f.class_id for f in raw} - {f.class_id for f in findings})
    return {
        "call_id": call.id,
        "scenario": call.scenario,
        "verdict": verdict.model_dump(mode="json"),
        "conv_cost_usd": priced.conv_cost,
        "stage_costs_usd": dict(priced.stage_costs),
        "coverage": {str(k): v for k, v in coverage.items()},
        "findings": [
            {**f.model_dump(mode="json"), "call_id": call.id} for f in findings
        ],
        "excluded_absent_classes": dropped,
        "n_turns": len(call.turns),
    }


def _recoverable_margin(priced_traces: list[PricedTrace], total_cost: float) -> float:
    """Same §8.3 gate as the dashboard's build_fleet: proven savings only
    when the D1-reroute replay preserves outcomes (>= 0.95) with a
    non-zero-crossing CI; otherwise 0.0 (no claim), never a guess."""
    if not priced_traces or not total_cost:
        return 0.0
    result = experiment(priced_traces, OVER_MODEL_VARIANT)
    ci_lo, ci_hi = result.delta_cost_ci95
    ci_confirms = (ci_lo < 0 and ci_hi < 0) or (ci_lo > 0 and ci_hi > 0)
    if result.outcome_preservation_rate >= 0.95 and ci_confirms:
        return -result.delta_cost_mean * result.n / total_cost * 100.0
    return 0.0


def run_calls(
    objs: list[dict[str, Any] | IngestCall],
    rates,
    baselines: Baselines,
    *,
    label: str,
    sample: bool,
) -> dict[str, Any]:
    """Run the full pipeline over many calls; return the dashboard-shaped
    data artifact (fleet + findings + per-call reports + coverage summary)."""
    priced_traces: list[PricedTrace] = []
    calls: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    total_cost = 0.0
    resolved_cost = 0.0
    n_resolved = 0
    stage_totals: dict[str, float] = {}

    for obj in objs:
        call, priced, verdict, coverage, findings, _raw = _run_priced(obj, rates, baselines)
        report = {
            "call_id": call.id,
            "scenario": call.scenario,
            "verdict": verdict.model_dump(mode="json"),
            "conv_cost_usd": priced.conv_cost,
            "stage_costs_usd": dict(priced.stage_costs),
            "coverage": {str(k): v for k, v in coverage.items()},
            "findings": [
                {**f.model_dump(mode="json"), "call_id": call.id} for f in findings
            ],
            "excluded_absent_classes": sorted(
                {f.class_id for f in _raw} - {f.class_id for f in findings}
            ),
            "n_turns": len(call.turns),
        }
        priced_traces.append(priced)
        calls.append(report)
        all_findings.extend(report["findings"])
        total_cost += priced.conv_cost
        for stage, cost in priced.stage_costs.items():
            stage_totals[stage] = stage_totals.get(stage, 0.0) + cost
        if report["verdict"]["label"] == "RESOLVED":
            resolved_cost += priced.conv_cost
            n_resolved += 1

    n = len(calls)
    acoustic_note = (
        "Calls without G2 acoustic fields (tts.chars_synthesized/chars_played) "
        "carry no TTS/playback spans: their TTS cost is unmeasured (0 in "
        "stage_costs, NOT zero waste) and detector classes 6/7/8 are reported "
        "ABSENT per call ('no data for this input'), excluded from findings."
    )
    fleet = {
        "label": label,
        "note": ("SAMPLE aggregate over ingested calls -- not a production fleet. " if sample else "")
        + "CPRC_naive/CPRC_loaded per PRD Sec.4.3. " + acoustic_note,
        "n_conversations": n,
        "n_resolved": n_resolved,
        "total_cost_usd": total_cost,
        "resolved_cost_usd": resolved_cost,
        "cprc_loaded": total_cost / n_resolved if n_resolved else 0.0,
        "cprc_naive": resolved_cost / n_resolved if n_resolved else 0.0,
        "recoverable_margin_pct": _recoverable_margin(priced_traces, total_cost),
        "stage_costs_usd": stage_totals,
        "_provenance": {
            "n": n,
            "sample": sample,
            "note": (
                "Ingested (non-synthetic) call logs via turnstile_ingest. LLM/tool "
                "layers measured from the log's own tokens and tool outcomes; "
                "acoustic layer (ASR/TTS/telephony) priced only where the log "
                "carries rate-resolvable telemetry. " + acoustic_note
            ),
        },
    }
    present_counts: dict[str, int] = {}
    for report in calls:
        for class_id, entry in report["coverage"].items():
            if entry["status"] == "present":
                present_counts[class_id] = present_counts.get(class_id, 0) + 1
    return {
        "label": label,
        "sample": sample,
        "fleet": fleet,
        "coverage_summary": {
            "n_calls": n,
            "calls_with_data_per_class": present_counts,
        },
        "calls": calls,
        "findings": all_findings,
    }
