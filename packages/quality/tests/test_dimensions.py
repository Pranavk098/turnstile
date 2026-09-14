"""Unit tests for the v1 quality dimensions (builders, not fixtures).

Each dimension is pinned on small synthetic traces: fires when it should,
silent when it shouldn't, with the tier/label contract from types.py.
Golden-fixture agreement lives in test_agreement.py.
"""
from __future__ import annotations

from _quality_builders import (
    _dims,
    _llm,
    _playback,
    _priced,
    _tool,
    _tts,
    _turn,
    _verdict,
)
from turnstile_schema.enums import (
    DecisionKind,
    Effect,
    EndReason,
    ToolKind,
    VerdictLabel,
)

from turnstile_quality import evaluate_quality
from turnstile_quality.dimensions import summarize_quality
from turnstile_quality.types import QualityReport


# -- task_success -----------------------------------------------------------

def test_task_success_pass_on_committed_mutation():
    priced = _priced(_turn(0, tools=[_tool("t0", name="process_refund")]))
    dim = _dims(priced, _verdict(VerdictLabel.RESOLVED))["task_success"]
    assert (dim.label, dim.score, dim.tier) == ("pass", 1.0, "measured")


def test_task_success_fail_on_uncommitted_effect():
    priced = _priced(_turn(0, tools=[_tool("t0", name="process_refund",
                                          effect=Effect.rejected)]))
    dim = _dims(priced, _verdict(VerdictLabel.UNRESOLVED))["task_success"]
    assert (dim.label, dim.score) == ("fail", 0.0)


def test_task_success_partial_on_partially_resolved():
    priced = _priced(_turn(0, tools=[_tool("t0", name="process_refund",
                                          effect=Effect.pending)]))
    dim = _dims(priced, _verdict(VerdictLabel.PARTIALLY_RESOLVED))["task_success"]
    assert (dim.label, dim.score) == ("partial", 0.5)


def test_task_success_fail_on_misroute_and_false_resolve():
    priced = _priced(_turn(0, tools=[_tool("t0", name="wrong_tool")]))
    misrouted = _dims(priced, _verdict(VerdictLabel.MISROUTED))["task_success"]
    assert misrouted.label == "fail"
    pending = _priced(_turn(0, tools=[_tool("t0", name="process_refund",
                                           effect=Effect.pending)]))
    false_resolve = _dims(pending, _verdict(VerdictLabel.FALSE_RESOLVE))["task_success"]
    assert false_resolve.label == "fail"


def test_task_success_informational_defers_to_verdict():
    priced = _priced(_turn(0, llm=[_llm("l0")]))
    assert _dims(priced, _verdict(VerdictLabel.RESOLVED))["task_success"].label == "pass"
    assert _dims(priced, _verdict(VerdictLabel.UNRESOLVED))["task_success"].label == "fail"


def test_task_success_escalated_needs_committed_handoff():
    esc = _turn(0, tools=[_tool("t0", name="transfer_to_agent",
                                kind=ToolKind.handoff)])
    priced = _priced(esc)
    assert _dims(priced, _verdict(VerdictLabel.ESCALATED))["task_success"].label == "pass"
    rej = _turn(0, tools=[_tool("t0", name="transfer_to_agent",
                                kind=ToolKind.handoff, effect=Effect.rejected)])
    priced_rej = _priced(rej)
    assert _dims(priced_rej, _verdict(VerdictLabel.UNRESOLVED))["task_success"].label == "fail"


# -- slot_completeness -------------------------------------------------------

def test_slot_completeness_fail_on_hangup_mid_solicitation():
    priced = _priced(_turn(0, llm=[_llm("l0", kind=DecisionKind.slot_fill,
                                       chosen="account_number",
                                       text="please tell me the number")]))
    dim = _dims(priced, _verdict(VerdictLabel.ABANDONED))["slot_completeness"]
    assert dim.label == "fail"
    assert dim.evidence["outstanding_solicitation"] is True


def test_slot_completeness_pass_with_clean_close():
    priced = _priced(_turn(0, llm=[_llm("l0", kind=DecisionKind.slot_fill,
                                       chosen="account_number",
                                       text="thanks, goodbye!")] ))
    dim = _dims(priced, _verdict(VerdictLabel.RESOLVED))["slot_completeness"]
    assert dim.label == "pass"


def test_slot_completeness_pass_when_not_soliciting_or_not_hangup():
    compose = _priced(_turn(0, llm=[_llm("l0", text="all done here")]))
    assert _dims(compose, _verdict(VerdictLabel.RESOLVED))["slot_completeness"].label == "pass"
    timeout = _priced(
        _turn(0, llm=[_llm("l0", kind=DecisionKind.slot_fill, chosen="pin",
                           text="your pin please")]),
        end_reason=EndReason.timeout,
    )
    assert _dims(timeout, _verdict(VerdictLabel.UNRESOLVED))["slot_completeness"].label == "pass"


# -- escalation_appropriateness ------------------------------------------------

def test_escalation_pass_signaled_handoff_same_turn_counts():
    t = _turn(0,
              llm=[_llm("l0", kind=DecisionKind.escalate_check, chosen="escalate",
                        text="let me get a specialist")],
              tools=[_tool("t0", name="transfer_to_agent", kind=ToolKind.handoff)])
    dim = _dims(_priced(t), _verdict(VerdictLabel.ESCALATED, turn_of_no_return=0))[
        "escalation_appropriateness"]
    assert dim.label == "pass"


def test_escalation_fail_cold_handoff():
    t = _turn(0,
              llm=[_llm("l0", text="transferring you now")],
              tools=[_tool("t0", name="transfer_to_agent", kind=ToolKind.handoff)])
    dim = _dims(_priced(t), _verdict(VerdictLabel.ESCALATED, turn_of_no_return=0))[
        "escalation_appropriateness"]
    assert dim.label == "fail"
    assert dim.evidence["signal_turns"] == []


def test_escalation_fail_stranded_despite_signal():
    t = _turn(0, llm=[_llm("l0", kind=DecisionKind.escalate_check,
                           chosen="escalate", text="let me escalate")])
    dim = _dims(_priced(t), _verdict(VerdictLabel.UNRESOLVED))[
        "escalation_appropriateness"]
    assert dim.label == "fail"


def test_escalation_pass_no_signal_no_handoff_and_talkdown():
    plain = _priced(_turn(0, llm=[_llm("l0", text="all good")]))
    assert _dims(plain, _verdict(VerdictLabel.RESOLVED))[
        "escalation_appropriateness"].label == "pass"
    talkdown = _priced(_turn(0, llm=[_llm("l0", kind=DecisionKind.escalate_check,
                                         chosen="continue",
                                         text="actually I can help")] ))
    assert _dims(talkdown, _verdict(VerdictLabel.RESOLVED))[
        "escalation_appropriateness"].label == "pass"


# -- barge_in_courtesy ----------------------------------------------------------

def test_barge_in_courtesy_pass_on_yield_and_absence():
    yielded = _priced(_turn(0, barge_in=True, tts=[_tts("t0")],
                            playback=[_playback("p0", truncated_by="barge_in")]))
    dim = _dims(yielded, _verdict(VerdictLabel.RESOLVED))["barge_in_courtesy"]
    assert (dim.label, dim.tier) == ("pass", "measured")
    quiet = _priced(_turn(0, llm=[_llm("l0")], tts=[_tts("t0")],
                          playback=[_playback("p0", truncated_by=None)]))
    dim_quiet = _dims(quiet, _verdict(VerdictLabel.RESOLVED))["barge_in_courtesy"]
    assert dim_quiet.label == "pass"
    assert dim_quiet.evidence["n_barge_turns"] == 0


def test_barge_in_courtesy_fail_on_talk_over():
    talked = _priced(_turn(0, barge_in=True, tts=[_tts("t0")],
                           playback=[_playback("p0", truncated_by=None)]))
    dim = _dims(talked, _verdict(VerdictLabel.RESOLVED))["barge_in_courtesy"]
    assert dim.label == "fail"
    assert dim.evidence["talked_over_turns"] == [0]


def test_barge_in_courtesy_unmeasured_without_playback():
    naked = _priced(_turn(0, barge_in=True, llm=[_llm("l0")]))
    dim = _dims(naked, _verdict(VerdictLabel.RESOLVED))["barge_in_courtesy"]
    assert (dim.label, dim.score, dim.tier) == ("unmeasured", None, "instrumented")


# -- non_repetition -------------------------------------------------------------

def test_non_repetition_fail_on_reprompt_and_thrash():
    reprompt = _priced(
        _turn(0, llm=[_llm("l0", kind=DecisionKind.slot_fill, chosen="pin",
                           text="your pin please")]),
        _turn(1, llm=[_llm("l1", kind=DecisionKind.slot_fill, chosen="pin",
                           text="your pin again please")], start=1000, end=2000),
    )
    dim = _dims(reprompt, _verdict(VerdictLabel.UNRESOLVED))["non_repetition"]
    assert dim.label == "fail"
    assert dim.evidence["reprompt_episode"]["reprompt_turn"] == 1
    thrash = _priced(_turn(0, tools=[_tool("t0", name="lookup_order")]),
                     _turn(1, tools=[_tool("t1", name="lookup_order")],
                           start=1000, end=2000))
    dim_thrash = _dims(thrash, _verdict(VerdictLabel.RESOLVED))["non_repetition"]
    assert dim_thrash.label == "fail"
    assert dim_thrash.evidence["duplicate_tool_calls"][0]["tool_name"] == "lookup_order"


def test_non_repetition_pass_on_clean_call():
    clean = _priced(
        _turn(0, llm=[_llm("l0", kind=DecisionKind.slot_fill, chosen="pin",
                           text="your pin please")]),
        _turn(1, llm=[_llm("l1", kind=DecisionKind.compose, chosen="done",
                           text="all set, thanks")], start=1000, end=2000),
    )
    assert _dims(clean, _verdict(VerdictLabel.RESOLVED))["non_repetition"].label == "pass"


# -- overall + summary ------------------------------------------------------------

def test_overall_pass_excludes_pending_judges():
    rep = evaluate_quality(_priced(_turn(0, llm=[_llm("l0")])),
                           _verdict(VerdictLabel.RESOLVED))
    assert rep.overall.label == "pass" and rep.overall.tier == "measured"
    pending_ids = [d.id for d in rep.dimensions if d.method == "judge_pending"]
    assert set(pending_ids) == {"faithfulness", "answer_relevance"}
    assert all(d.score is None and d.label == "pending" for d in rep.dimensions
               if d.id in pending_ids)


def test_overall_fail_beats_partial():
    """PARTIALLY_RESOLVED (task partial) plus a hanging slot solicitation
    (slot fail) rolls up to fail, not partial."""
    priced = _priced(
        _turn(0, tools=[_tool("t0", name="process_refund", effect=Effect.pending)]),
        _turn(1, llm=[_llm("l1", kind=DecisionKind.slot_fill, chosen="pin",
                           text="your pin please")], start=1000, end=2000),
    )
    rep = evaluate_quality(priced, _verdict(VerdictLabel.PARTIALLY_RESOLVED))
    assert rep.by_id("task_success").label == "partial"
    assert rep.by_id("slot_completeness").label == "fail"
    assert rep.overall.label == "fail"


def test_overall_partial_without_fail():
    priced = _priced(
        _turn(0, tools=[_tool("t0", name="process_refund", effect=Effect.pending)]),
        _turn(1, llm=[_llm("l1", text="submitted, thanks, goodbye")],
              start=1000, end=2000),
    )
    rep = evaluate_quality(priced, _verdict(VerdictLabel.PARTIALLY_RESOLVED))
    assert rep.by_id("task_success").label == "partial"
    assert rep.overall.label == "partial"


def test_summarize_quality_format():
    assert summarize_quality("pass", "measured", 1.34) == "quality: pass (measured) · cost $1.34"
    assert summarize_quality("fail", "measured", 0.2).startswith("quality: fail")


def test_report_json_round_trip():
    rep = evaluate_quality(_priced(_turn(0, llm=[_llm("l0")])),
                           _verdict(VerdictLabel.RESOLVED))
    dumped = QualityReport.model_validate(rep.model_dump(mode="json"))
    assert dumped == rep
    assert rep.by_id("task_success").label == "pass"
    try:
        rep.by_id("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("by_id must raise KeyError on unknown id")
