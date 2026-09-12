"""Scale probe set + Wilson CIs + divergence-mix tests (TDD -- red first).

V7-V12 (36 probes) bait real divergence: cue-less opens the mock routes to
"other", cross-scenario cue words that misroute the mock's first-match
keyword order, and question-opens -- balanced with likely-convergent
escalate/verbose variants. The figures gain Wilson CIs; divergences get a
mix classification (turn0-label vs action-level) so the report can say WHAT
diverged, not just how much.
"""
from __future__ import annotations

from turnstile_live.openloop import (
    EXTRA_SCRIPTS,
    EXTRA_SCRIPTS_2,
    SCRIPT_SET,
    classify_divergence,
    summarize,
)


def test_scale_scripts_extend_without_touching_frozen_sets():
    assert len(SCRIPT_SET) == 24  # P3's frozen gate
    assert len(EXTRA_SCRIPTS) == 12  # P5's frozen extension
    assert len(EXTRA_SCRIPTS_2) == 36
    base_ids = {c.id for c in SCRIPT_SET} | {c.id for c in EXTRA_SCRIPTS}
    by_scenario: dict[str, int] = {}
    for conv in EXTRA_SCRIPTS_2:
        by_scenario[conv.scenario] = by_scenario.get(conv.scenario, 0) + 1
        assert len(conv.caller_texts) == 3
        assert conv.id not in base_ids
        base_ids.add(conv.id)
        assert conv.id.split("-")[-1] in {"v7", "v8", "v9", "v10", "v11", "v12"}
    assert set(by_scenario.values()) == {6}


def test_summarize_adds_wilson_cis():
    rows = [
        {"divergent": True, "rule1": True, "rule2": True},
        {"divergent": True, "rule1": True, "rule2": False},
        {"divergent": True, "rule1": False, "rule2": False},
        {"divergent": True, "rule1": None, "rule2": False},
        {"divergent": False, "rule1": None, "rule2": None},
    ]
    figures = summarize(rows)
    assert figures["n_divergent"] == 4
    assert figures["registry"] == 2 / 3
    lo, hi = figures["registry_ci95"]
    assert lo <= 2 / 3 <= hi
    assert figures["llm_judge"] == 0.25
    lo, hi = figures["llm_judge_ci95"]
    assert lo <= 0.25 <= hi
    # Old keys still exact (no silent redefinition of the figures).
    assert figures["n_undecidable"] == 1
    assert figures["n_judge_unparsed"] == 0


def test_summarize_ci_is_none_without_denominator():
    figures = summarize([{"divergent": False, "rule1": None, "rule2": None}])
    assert figures["registry"] is None
    assert figures["registry_ci95"] is None
    assert figures["llm_judge_ci95"] is None


def test_classify_divergence():
    base = [("route", "refund"), ("compose", "inform"), ("compose", "close_call")]
    assert classify_divergence(base, base) == "converged"
    assert classify_divergence(
        base, [("route", "other"), ("compose", "inform"), ("compose", "close_call")]
    ) == "turn0-label"
    assert classify_divergence(
        base, [("route", "refund"), ("tool_select", "process_refund"), ("compose", "close_call")]
    ) == "action-level"
    assert classify_divergence(
        base, [("route", "billing_dispute"), ("compose", "inform"), ("compose", "close_call")]
    ) == "turn0-label"
