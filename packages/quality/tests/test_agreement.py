"""Golden-fixture agreement: quality never contradicts the existing layers.

* task_success tracks the verdict's terminal-tool evidence on every golden
  trace (independently re-derived here, so drift fails loudly);
* non_repetition agrees with detect() classes 5/10 on every golden trace;
* the fixtures engineered for a dimension read as intended.
"""
from __future__ import annotations

from pathlib import Path

from turnstile_detectors import detect
from turnstile_pricing import price_trace
from turnstile_schema import Baselines, VerdictLabel, load_rates, load_trace
from turnstile_schema.enums import Effect, ToolKind
from turnstile_verdict import adjudicate

from turnstile_quality import evaluate_quality

ROOT = Path(__file__).resolve().parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
EMPTY_BASELINES = Baselines(per_intent={})


def _goldens():
    return sorted(
        p for p in (ROOT / "fixtures" / "golden").glob("*.json")
        if not p.name.startswith("_")
    )


def _evaluated(path: Path):
    priced = price_trace(load_trace(path), RATES)
    verdict = adjudicate(priced)
    return priced, verdict, evaluate_quality(priced, verdict)


def _expected_task_success(priced, verdict) -> str:
    """Independent re-derivation of the task_success rule (mirrors the
    dimension's contract, not its code): terminal mutating span vs verdict."""
    terminal = None
    for turn in priced.trace.turns:
        for tool in turn.tools:
            if tool.tool_kind in (ToolKind.mutation, ToolKind.handoff):
                terminal = tool
    label = verdict.label
    if terminal is None:
        return "pass" if label is VerdictLabel.RESOLVED else "fail"
    if label is VerdictLabel.PARTIALLY_RESOLVED:
        return "partial"
    if label is VerdictLabel.RESOLVED and terminal.tool_kind is ToolKind.mutation \
            and terminal.effect is Effect.committed:
        return "pass"
    if label is VerdictLabel.ESCALATED and terminal.tool_kind is ToolKind.handoff \
            and terminal.effect is Effect.committed:
        return "pass"
    return "fail"


def test_task_success_agrees_with_verdict_on_all_goldens():
    for path in _goldens():
        priced, verdict, report = _evaluated(path)
        assert report.by_id("task_success").label == _expected_task_success(priced, verdict), \
            path.stem


def test_non_repetition_agrees_with_d5_d10_on_all_goldens():
    for path in _goldens():
        priced, verdict, report = _evaluated(path)
        classes = {f.class_id for f in detect(priced, verdict, EMPTY_BASELINES)}
        expect_fail = bool(classes & {5, 10})
        assert (report.by_id("non_repetition").label == "fail") == expect_fail, path.stem


def test_engineered_fixtures_read_as_intended():
    expectations = {
        # fixture: (overall, {dim_id: label} for the engineered dimensions)
        "00_baseline_clean": ("pass", {}),
        "05_reprompt_loop": ("fail", {"non_repetition": "fail"}),
        "07_barge_in_waste": ("pass", {"barge_in_courtesy": "pass"}),
        "09_escalation_debt": ("pass", {"escalation_appropriateness": "pass"}),
        "10_tool_thrash": ("fail", {"non_repetition": "fail",
                                    "task_success": "pass"}),
        "14_escalation_early": ("pass", {"escalation_appropriateness": "pass"}),
        "15_escalation_late": ("pass", {"escalation_appropriateness": "pass"}),
        "16_abandoned": ("fail", {"task_success": "fail",
                                  "slot_completeness": "fail"}),
        "17_false_resolve": ("fail", {"task_success": "fail"}),
    }
    by_stem = {p.stem: p for p in _goldens()}
    for stem, (overall, dims) in expectations.items():
        _, _, report = _evaluated(by_stem[stem])
        assert report.overall.label == overall, stem
        for dim_id, label in dims.items():
            assert report.by_id(dim_id).label == label, (stem, dim_id)


def test_pending_judges_never_score_on_goldens():
    for path in _goldens():
        _, _, report = _evaluated(path)
        for dim_id in ("faithfulness", "answer_relevance"):
            dim = report.by_id(dim_id)
            assert dim.score is None
            assert dim.label == "pending"
            assert dim.tier == "not_measured"
            assert dim.method == "judge_pending"


def test_overall_tier_is_measured_on_goldens():
    for path in _goldens():
        _, _, report = _evaluated(path)
        assert report.overall.tier == "measured", path.stem
