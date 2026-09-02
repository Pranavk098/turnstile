"""Tests for the Resolution Ledger (packages/verdict).

Two layers:
  * Fixture layer -- adjudicate() over the 23 golden fixtures: spec-pinned labels
    are asserted exactly; the rest must merely return a valid VerdictLabel.
  * Unit layer -- one synthetic trace per binding v1.1 rule.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from turnstile_schema import PricedTrace, load_trace
from turnstile_schema.enums import (
    DecisionKind,
    Effect,
    EndReason,
    ToolKind,
    ToolStatus,
    VerdictLabel,
)
from turnstile_schema.spans import LlmDecide, ToolCall
from turnstile_schema.trace import Conversation, Trace, Turn
from turnstile_verdict import adjudicate
from turnstile_verdict.adjudicate import UNKNOWN_CONFIDENCE_CAP

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"

# Fixtures whose expected_verdict is spec-derivable (acceptance criteria). The
# rest of the manifest's expected_verdicts are best-judgment placeholders -- for
# those we only assert a valid label is returned.
PINNED = {
    "00_baseline_clean": VerdictLabel.RESOLVED,
    "09_escalation_debt": VerdictLabel.ESCALATED,
    "14_escalation_early": VerdictLabel.ESCALATED,
    "15_escalation_late": VerdictLabel.ESCALATED,
    "16_abandoned": VerdictLabel.ABANDONED,
    "17_false_resolve": VerdictLabel.FALSE_RESOLVE,
    "21_handoff_rejected": VerdictLabel.UNRESOLVED,
    "22_handoff_pending": VerdictLabel.UNRESOLVED,
}


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _priced(trace: Trace) -> PricedTrace:
    """Wrap a Trace in a zero-cost PricedTrace. adjudicate() never reads costs;
    this validates outcome logic only."""
    span_ids: list[str] = []
    for turn in trace.turns:
        for group in (turn.vad, turn.asr, turn.llm, turn.tools, turn.tts, turn.playback):
            span_ids.extend(s.span_id for s in group)
        if turn.context is not None:
            span_ids.append(turn.context.span_id)
    return PricedTrace(
        trace=trace,
        span_costs={sid: 0.0 for sid in span_ids},
        turn_costs=[0.0] * len(trace.turns),
        conv_cost=0.0,
        stage_costs={"asr": 0.0, "llm": 0.0, "tts": 0.0, "telephony": 0.0},
    )


def _fixture(name: str) -> PricedTrace:
    return _priced(load_trace((GOLDEN / name).with_suffix(".json")))


def _all_fixture_ids() -> list[str]:
    fixtures = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
    return [f["id"] for f in fixtures]


# -- synthetic-trace builders for the unit layer ---------------------------- #

def _tool(kind: ToolKind, effect: Effect, status: ToolStatus = ToolStatus.ok) -> ToolCall:
    return ToolCall(
        span_id="tool1", start_offset_ms=0, duration_ms=100,
        tool_name="t", args_hash="sha256:a", args_json="{}",
        result_hash="sha256:b", latency_ms=100,
        tool_kind=kind, tool_status=status, effect=effect,
    )


def _llm(text: str, decision_kind: DecisionKind = DecisionKind.compose) -> LlmDecide:
    return LlmDecide(
        span_id="llm1", start_offset_ms=0, duration_ms=100,
        gen_ai_system="openai", gen_ai_request_model="gpt-5",
        input_tokens=10, output_tokens=10,
        decision_kind=decision_kind, decision_chosen="x", decision_candidates=["x"],
        output_text=text, latency_ms=100,
    )


def _synthetic(
    *, tool: ToolCall | None = None, llm_text: str = "ok",
    decision_kind: DecisionKind = DecisionKind.compose,
    end_reason: EndReason = EndReason.caller_hangup,
) -> PricedTrace:
    turn = Turn(
        turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=1000,
        llm=[_llm(llm_text, decision_kind)],
        tools=[tool] if tool is not None else [],
    )
    trace = Trace(
        conversation=Conversation(
            conversation_id="c1", agent_version="v1", scenario_id="s1",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            end_reason=end_reason,
        ),
        turns=[turn],
    )
    return _priced(trace)


# --------------------------------------------------------------------------- #
# Fixture layer                                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fid", _all_fixture_ids())
def test_adjudicate_runs_and_returns_valid_label(fid):
    verdict = adjudicate(_fixture(fid))
    assert isinstance(verdict.label, VerdictLabel)
    assert 0.0 <= verdict.confidence <= 1.0
    assert isinstance(verdict.evidence, list) and verdict.evidence


@pytest.mark.parametrize("fid,expected", sorted(PINNED.items()))
def test_pinned_fixtures_match_expected_label(fid, expected):
    assert adjudicate(_fixture(fid)).label is expected


@pytest.mark.parametrize("fid,expected_turn", [
    ("09_escalation_debt", 3),   # escalate_check at turn 3, handoff at turn 12
    ("14_escalation_early", 3),  # escalate_check and handoff both at turn 3
    ("15_escalation_late", 6),   # escalate_check at turn 6, handoff at turn 7
])
def test_escalated_golden_fixtures_turn_of_no_return_is_escalate_check_turn(fid, expected_turn):
    v = adjudicate(_fixture(fid))
    assert v.label is VerdictLabel.ESCALATED
    assert v.turn_of_no_return == expected_turn


def test_fixture_20_unknown_mutation_caps_confidence_and_restricts_label():
    v = adjudicate(_fixture("20_unknown_mutation"))
    assert v.label not in (VerdictLabel.RESOLVED, VerdictLabel.FALSE_RESOLVE)
    assert v.confidence <= UNKNOWN_CONFIDENCE_CAP
    assert any(e.get("effect") == "unknown" for e in v.evidence)


def test_pinned_labels_agree_with_manifest_expected_verdict():
    """Guard: the spec-pinned expectations here match the manifest ground truth."""
    fixtures = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
    by_id = {f["id"]: f["expected_verdict"] for f in fixtures}
    for fid, expected in PINNED.items():
        assert by_id[fid] == expected.value, fid


# --------------------------------------------------------------------------- #
# Unit layer -- one synthetic trace per binding v1.1 rule                       #
# --------------------------------------------------------------------------- #

def test_committed_mutation_is_resolved():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.mutation, Effect.committed),
                              llm_text="All done."))
    assert v.label is VerdictLabel.RESOLVED
    assert v.confidence > UNKNOWN_CONFIDENCE_CAP


def test_rejected_mutation_with_completion_assertion_is_false_resolve():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.mutation, Effect.rejected),
                              llm_text="Your refund is processed."))
    assert v.label is VerdictLabel.FALSE_RESOLVE


def test_pending_mutation_with_completion_assertion_is_false_resolve():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.mutation, Effect.pending),
                              llm_text="All set, that's completed."))
    assert v.label is VerdictLabel.FALSE_RESOLVE


def test_rejected_mutation_without_assertion_is_unresolved():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.mutation, Effect.rejected),
                              llm_text="I couldn't do that."))
    assert v.label is VerdictLabel.UNRESOLVED


def test_unknown_mutation_caps_confidence_and_forbids_resolved_and_false_resolve():
    # Even with a completion assertion, unknown must not become FALSE_RESOLVE.
    v = adjudicate(_synthetic(
        tool=_tool(ToolKind.mutation, Effect.unknown, ToolStatus.error),
        llm_text="Your cancellation is processed."))
    assert v.label not in (VerdictLabel.RESOLVED, VerdictLabel.FALSE_RESOLVE)
    assert v.confidence <= UNKNOWN_CONFIDENCE_CAP
    assert any(e.get("effect") == "unknown" for e in v.evidence)


def test_committed_handoff_is_escalated():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.handoff, Effect.committed),
                              end_reason=EndReason.escalated))
    assert v.label is VerdictLabel.ESCALATED


def test_committed_handoff_without_escalate_check_falls_back_to_handoff_turn():
    """No escalate_check span anywhere -- turn_of_no_return stays the handoff's
    own turn (the pre-fix behavior), per the documented fallback."""
    v = adjudicate(_synthetic(tool=_tool(ToolKind.handoff, Effect.committed),
                              end_reason=EndReason.escalated))
    assert v.label is VerdictLabel.ESCALATED
    assert v.turn_of_no_return == 0


def test_escalated_turn_of_no_return_is_earliest_escalate_check_turn():
    """GAP-05 fix: for ESCALATED, turn_of_no_return should be the earliest
    escalate_check turn, not the (later) handoff turn -- the Wave-1
    deterministic stand-in for the escalation classifier (PRD Sec.6 D9)."""
    turns = [
        Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=500,
             llm=[_llm("stalling", DecisionKind.compose)]),
        Turn(turn_index=1, speaker_first="agent", wall_start_ms=500, wall_end_ms=1000,
             llm=[_llm("escalation looks likely", DecisionKind.escalate_check)]),
        Turn(turn_index=2, speaker_first="agent", wall_start_ms=1000, wall_end_ms=1500,
             llm=[_llm("still stalling", DecisionKind.compose)]),
        Turn(turn_index=3, speaker_first="agent", wall_start_ms=1500, wall_end_ms=2000,
             llm=[_llm("transferring", DecisionKind.compose)],
             tools=[_tool(ToolKind.handoff, Effect.committed)]),
    ]
    trace = Trace(
        conversation=Conversation(
            conversation_id="c1", agent_version="v1", scenario_id="s1",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ended_at=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            end_reason=EndReason.escalated,
        ),
        turns=turns,
    )
    v = adjudicate(_priced(trace))
    assert v.label is VerdictLabel.ESCALATED
    assert v.turn_of_no_return == 1  # earliest escalate_check turn, not turn 3


def test_rejected_handoff_is_unresolved_not_escalated():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.handoff, Effect.rejected)))
    assert v.label is VerdictLabel.UNRESOLVED


def test_pending_handoff_is_unresolved_not_escalated():
    v = adjudicate(_synthetic(tool=_tool(ToolKind.handoff, Effect.pending),
                              end_reason=EndReason.escalated))
    assert v.label is VerdictLabel.UNRESOLVED


def test_caller_hangup_mid_slot_fill_is_abandoned():
    v = adjudicate(_synthetic(llm_text="Can I get your order number?",
                              decision_kind=DecisionKind.slot_fill))
    assert v.label is VerdictLabel.ABANDONED
    assert v.turn_of_no_return == 0


def test_informational_resolution_leaves_turn_of_no_return_none():
    v = adjudicate(_synthetic(llm_text="Your order ships tomorrow. Goodbye."))
    assert v.label is VerdictLabel.RESOLVED
    assert v.turn_of_no_return is None


# -- non-clean end on the informational path (Section B2) -------------------- #

@pytest.mark.parametrize("reason", [EndReason.timeout, EndReason.error, EndReason.agent_hangup])
def test_non_clean_end_on_informational_path_is_not_resolved(reason):
    """The sharpest confidently-wrong edge: an informational-intent trace that
    ends non-cleanly must NOT default to RESOLVED@0.70 -- the call may have
    died before the intent was served. Matching the unknown-handling style:
    UNRESOLVED with confidence capped at the unknown cap, rule in evidence."""
    v = adjudicate(_synthetic(llm_text="Your order ships tomorrow.", end_reason=reason))
    assert v.label is VerdictLabel.UNRESOLVED
    assert v.confidence <= UNKNOWN_CONFIDENCE_CAP
    assert any(e.get("rule") == "non_clean_end_blocks_informational_resolution"
               for e in v.evidence)
    assert v.evidence[0]["end_reason"] == reason.value


def test_non_clean_end_blocks_resolved_even_with_a_clean_close_utterance():
    # A courtesy goodbye in the tail does not make a timeout a resolution --
    # the doc's rule is absolute on the informational path.
    v = adjudicate(_synthetic(llm_text="Glad I could help. Goodbye!",
                              end_reason=EndReason.timeout))
    assert v.label is VerdictLabel.UNRESOLVED
    assert v.confidence <= UNKNOWN_CONFIDENCE_CAP
    assert v.evidence[0]["clean_close"] is True


def test_clean_end_informational_path_still_resolves():
    # Regression guard: caller_hangup stays a legitimate informational close.
    v = adjudicate(_synthetic(llm_text="Your order ships tomorrow. Goodbye.",
                              end_reason=EndReason.caller_hangup))
    assert v.label is VerdictLabel.RESOLVED
    assert v.confidence > UNKNOWN_CONFIDENCE_CAP
