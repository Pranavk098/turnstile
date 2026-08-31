"""Unit tests for Detector 9 -- escalation debt (PRD §6 row 9; schema v1.1 amendment)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import Verdict, load_rates, load_trace
from turnstile_schema.enums import ToolKind, VerdictLabel
from turnstile_pricing import price_trace
from turnstile_detectors.d09_escalation_debt import detect_escalation_debt

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, llm, priced, tool, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_tier1_fires_when_escalated_with_turn_of_no_return():
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=600, output_tokens=16)]),
        turn(1, 500, 1000, llm_spans=[llm("l1", start=500, input_tokens=600, output_tokens=16)]),
        turn(2, 1000, 1500, tools=[tool("tool2", start=1000, name="transfer_to_agent",
                                         kind=ToolKind.handoff, effect="committed")],
             llm_spans=[llm("l2", start=1000, input_tokens=650, output_tokens=18)]),
    )
    verdict = Verdict(label=VerdictLabel.ESCALATED, confidence=0.9, evidence=[], turn_of_no_return=1)
    findings = detect_escalation_debt(pt, verdict, EMPTY_BASELINES)
    tier1 = [f for f in findings if f.evidence["tier"] == 1]
    assert len(tier1) == 1
    f = tier1[0]
    assert f.class_id == 9
    assert f.turn_index == 1
    assert f.proposed_variant.escalation_policy == "threshold:0.85"
    assert f.waste_usd == pytest.approx(sum(pt.turn_costs[1:]))


def test_tier1_silent_when_not_escalated():
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=600, output_tokens=16)]),
    )
    verdict = Verdict(label=VerdictLabel.RESOLVED, confidence=0.9, evidence=[], turn_of_no_return=0)
    assert detect_escalation_debt(pt, verdict, EMPTY_BASELINES) == []


def test_tier2_fires_on_rejected_terminal_handoff_regardless_of_verdict():
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=600, output_tokens=16)]),
        turn(1, 500, 1000, tools=[tool("tool1", start=500, name="transfer_to_agent",
                                        kind=ToolKind.handoff, effect="rejected")],
             llm_spans=[llm("l1", start=500, input_tokens=650, output_tokens=18)]),
    )
    # Deliberately pass the DUMMY (RESOLVED) verdict -- tier 2 must not depend on
    # verdict.label (a rejected handoff actually adjudicates to UNRESOLVED, never
    # ESCALATED; this proves tier 2 reads the trace directly).
    findings = detect_escalation_debt(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    tier2 = [f for f in findings if f.evidence["tier"] == 2]
    assert len(tier2) == 1
    f = tier2[0]
    assert f.class_id == 9
    assert f.turn_index == 1 and f.span_id == "tool1"
    assert f.waste_usd == pytest.approx(pt.conv_cost)


def test_tier2_silent_on_pending_handoff():
    pt = priced(
        turn(0, 0, 500, tools=[tool("tool0", start=0, name="transfer_to_agent",
                                     kind=ToolKind.handoff, effect="pending")],
             llm_spans=[llm("l0", start=0, input_tokens=600, output_tokens=16)]),
    )
    assert detect_escalation_debt(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_no_handoff_and_not_escalated():
    pt = priced(
        turn(0, 0, 500, llm_spans=[llm("l0", start=0, input_tokens=600, output_tokens=16)]),
    )
    assert detect_escalation_debt(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


@pytest.mark.parametrize("fid,expected_turn_of_no_return", [
    # GAP-05 fix: turn_of_no_return is the earliest escalate_check turn, not
    # the terminal handoff's own turn. 09's escalate_check (turn 3) precedes
    # its handoff (turn 12) by 9 turns, so tier-1 debt should now span most
    # of the conversation rather than collapsing to the single handoff turn.
    ("09_escalation_debt", 3),
    ("14_escalation_early", 3),   # escalate_check and handoff both at turn 3
    ("15_escalation_late", 6),    # escalate_check at turn 6, handoff at turn 7
])
def test_golden_escalated_fixtures_fire_tier1(fid, expected_turn_of_no_return):
    from turnstile_verdict import adjudicate
    pt = price_trace(load_trace(GOLDEN / f"{fid}.json"), load_rates(RATES))
    verdict = adjudicate(pt)
    assert verdict.label is VerdictLabel.ESCALATED
    assert verdict.turn_of_no_return == expected_turn_of_no_return, fid
    findings = detect_escalation_debt(pt, verdict, EMPTY_BASELINES)
    tier1 = [f for f in findings if f.evidence["tier"] == 1]
    assert len(tier1) == 1, fid
    f = tier1[0]
    turns = pt.trace.turns
    t_pos = next(i for i, turn in enumerate(turns) if turn.turn_index == expected_turn_of_no_return)
    expected_waste = sum(pt.turn_costs[t_pos:])
    assert expected_waste > 0
    assert f.waste_usd == pytest.approx(expected_waste), fid
    assert f.turn_index == expected_turn_of_no_return


def test_golden_fixture_09_tier1_debt_spans_predictable_escalation_not_one_turn():
    """GAP-05 fix regression: 09's narrative is "predictable at turn 3, ran 9
    more turns" (escalate_check at turn 3, handoff at turn 12). Tier-1 debt
    must now cover turns [3..12], not collapse to the single handoff turn."""
    from turnstile_verdict import adjudicate
    pt = price_trace(load_trace(GOLDEN / "09_escalation_debt.json"), load_rates(RATES))
    verdict = adjudicate(pt)
    assert verdict.turn_of_no_return == 3
    findings = detect_escalation_debt(pt, verdict, EMPTY_BASELINES)
    tier1 = [f for f in findings if f.evidence["tier"] == 1]
    assert len(tier1) == 1
    f = tier1[0]
    single_turn_debt = pt.turn_costs[-1]  # what the pre-fix behavior would have yielded
    assert f.waste_usd > single_turn_debt * 5  # materially larger, not ~one turn's cost
    assert f.waste_usd == pytest.approx(sum(pt.turn_costs[3:]))
    assert f.waste_usd == pytest.approx(0.014233628352490422)


def test_golden_fixture_21_handoff_rejected_fires_tier2_full_conv_cost():
    from turnstile_verdict import adjudicate
    pt = price_trace(load_trace(GOLDEN / "21_handoff_rejected.json"), load_rates(RATES))
    verdict = adjudicate(pt)
    assert verdict.label is VerdictLabel.UNRESOLVED  # rejected handoff, never ESCALATED
    findings = detect_escalation_debt(pt, verdict, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.evidence["tier"] == 2
    assert f.waste_usd == pytest.approx(pt.conv_cost)


def test_golden_fixture_22_handoff_pending_stays_silent():
    from turnstile_verdict import adjudicate
    pt = price_trace(load_trace(GOLDEN / "22_handoff_pending.json"), load_rates(RATES))
    verdict = adjudicate(pt)
    assert detect_escalation_debt(pt, verdict, EMPTY_BASELINES) == []
