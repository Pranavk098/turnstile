"""v1 quality dimensions (PRD 04 §4.1-4.2) + the ``evaluate_quality`` entry point.

Every deterministic dimension derives ONLY from data the priced trace and
verdict already carry -- the same evidence the verdict layer and detectors
read, so quality is consistent with the rest of the tool by construction,
never a parallel truth:

* ``task_success`` -- the verdict's terminal-tool evidence, re-read from the
  trace (not copied from the verdict label), then agreement-tested.
* ``slot_completeness`` -- no outstanding slot solicitation at call end,
  reusing the verdict layer's public solicitation constants (one definition
  of "soliciting", not two).
* ``escalation_appropriateness`` -- a handoff happened iff an escalation
  signal (``escalate_check``) preceded it; promptness is D9's waste finding,
  not this dimension (stated boundary).
* ``barge_in_courtesy`` -- on barge-in turns with observable playback, the
  agent stopped speaking (``truncated_by="barge_in"``) vs played through.
  Without playback spans there is nothing to observe: ``instrumented`` /
  ``unmeasured``, never faked.
* ``non_repetition`` -- the D5/D10 structural cores (adjacent same-slot
  ``slot_fill`` repeat; duplicate ``(tool_name, args_hash)``), with
  agreement tests against ``detect()`` binding them to the detectors.

The two judge dimensions (``faithfulness``, ``answer_relevance``) are
declared no-ops: ``score=None, tier="not_measured", method="judge_pending"``.
See ``calibration.py`` for the gate that must pass before any future scorer
may emit.
"""
from __future__ import annotations

from turnstile_schema import PricedTrace, Verdict
from turnstile_schema.enums import DecisionKind, Effect, EndReason, ToolKind, VerdictLabel
from turnstile_verdict.adjudicate import (
    CLOSING_KEYWORDS,
    CONFIRMATION_WINDOW_TURNS,
    SOLICITING_DECISION_KINDS,
)

from turnstile_quality.calibration import JUDGE_DIMENSIONS
from turnstile_quality.types import (
    SCORE_FAIL,
    SCORE_PARTIAL,
    SCORE_PASS,
    QualityDimension,
    QualityOverall,
    QualityReport,
)

_MUTATING_KINDS = (ToolKind.mutation, ToolKind.handoff)


def _terminal_mutating(trace) -> tuple[int, object] | None:
    """Last mutation/handoff span in document order (the verdict's own
    terminal-mutation convention, mirrored read-only)."""
    found = None
    for turn in trace.turns:
        for tool in turn.tools:
            if tool.tool_kind in _MUTATING_KINDS:
                found = (turn.turn_index, tool)
    return found


def _final_llm(trace):
    """(turn_index, last llm.decide span), or None when the trace has none."""
    found = None
    for turn in trace.turns:
        for llm in turn.llm:
            found = (turn.turn_index, llm)
    return found


def _has_clean_close(trace) -> bool:
    """Caller-confirmation / clean-close utterance in the final N turns --
    same window and keywords as the verdict layer (imported, not copied)."""
    tail = trace.turns[-CONFIRMATION_WINDOW_TURNS:]
    for turn in tail:
        for llm in turn.llm:
            low = llm.output_text.lower()
            if any(kw in low for kw in CLOSING_KEYWORDS):
                return True
    return False


def _task_success(priced: PricedTrace, verdict: Verdict) -> QualityDimension:
    """Task success re-read from the trace's terminal tool state.

    Passes exactly when the verdict's source-1 evidence passes: a committed
    terminal mutation for RESOLVED, a committed terminal handoff for
    ESCALATED, a served informational intent otherwise. MISROUTED and
    FALSE_RESOLVE fail by construction (wrong tool / uncommitted effect).
    """
    trace = priced.trace
    terminal = _terminal_mutating(trace)
    label = verdict.label
    if terminal is None:
        # Informational intent: no mutation to commit; served iff RESOLVED.
        passed = label is VerdictLabel.RESOLVED
        return QualityDimension(
            id="task_success",
            score=SCORE_PASS if passed else SCORE_FAIL,
            label="pass" if passed else "fail",
            tier="measured",
            evidence={
                "terminal_tool": None,
                "verdict_label": label.value,
                "rule": "informational intent defers to verdict sources 2-4",
            },
            method="deterministic",
        )
    turn_index, tool = terminal
    if label is VerdictLabel.PARTIALLY_RESOLVED:
        dim_label, score = "partial", SCORE_PARTIAL
    elif (
        (label is VerdictLabel.RESOLVED and tool.tool_kind is ToolKind.mutation
         and tool.effect is Effect.committed)
        or (label is VerdictLabel.ESCALATED and tool.tool_kind is ToolKind.handoff
            and tool.effect is Effect.committed)
    ):
        dim_label, score = "pass", SCORE_PASS
    else:
        dim_label, score = "fail", SCORE_FAIL
    return QualityDimension(
        id="task_success",
        score=score,
        label=dim_label,
        tier="measured",
        evidence={
            "terminal_tool": tool.tool_name,
            "terminal_kind": tool.tool_kind.value,
            "terminal_effect": tool.effect.value,
            "terminal_turn": turn_index,
            "verdict_label": label.value,
            "rule": "terminal required mutation/handoff committed iff resolved/escalated",
        },
        method="deterministic",
    )


def _slot_completeness(priced: PricedTrace, verdict: Verdict) -> QualityDimension:
    """No outstanding slot solicitation at call end.

    Fails exactly when the caller hung up while the agent was still asking
    for a required slot with no clean close -- the verdict's own ABANDONED
    condition, re-read from the trace. There is no slot registry to consult
    (stated boundary), so this dimension claims nothing about *which* slots
    were filled, only that none was left hanging at hangup.
    """
    trace = priced.trace
    final = _final_llm(trace)
    outstanding = (
        final is not None
        and trace.conversation.end_reason is EndReason.caller_hangup
        and final[1].decision_kind in SOLICITING_DECISION_KINDS
        and not _has_clean_close(trace)
    )
    return QualityDimension(
        id="slot_completeness",
        score=SCORE_FAIL if outstanding else SCORE_PASS,
        label="fail" if outstanding else "pass",
        tier="measured",
        evidence={
            "outstanding_solicitation": outstanding,
            "final_decision_kind": final[1].decision_kind.value if final else None,
            "final_turn": final[0] if final else None,
            "end_reason": trace.conversation.end_reason.value,
            "clean_close": _has_clean_close(trace),
            "verdict_label": verdict.label.value,
            "rule": "no slot_fill solicitation left hanging at caller hangup",
        },
        method="deterministic",
    )


def _escalation_signals(trace) -> list[int]:
    """Turn indexes carrying an ``escalate_check`` decision (the deterministic
    escalation-signal proxy the verdict layer itself uses for
    ``turn_of_no_return``)."""
    turns = []
    for turn in trace.turns:
        for llm in turn.llm:
            if llm.decision_kind is DecisionKind.escalate_check:
                turns.append(turn.turn_index)
                break
    return turns


def _escalation_appropriateness(priced: PricedTrace, verdict: Verdict) -> QualityDimension:
    """A handoff happened iff an escalation signal was present.

    * handoff span(s) + an ``escalate_check`` signal at or before the first
      handoff turn (attempted or committed, same turn counts -- deciding and
      acting together still shows its work) -> pass;
    * handoff span(s) with no signal anywhere -> fail (cold handoff);
    * no handoff + (no signal, or the call resolved anyway) -> pass;
    * no handoff + signal + UNRESOLVED/ABANDONED end -> fail (stranded caller).
    Promptness is NOT judged here -- a late-but-signaled handoff passes and
    D9 prices the delay as waste (stated boundary).
    """
    trace = priced.trace
    handoff_turns = sorted({
        turn.turn_index for turn in trace.turns
        for tool in turn.tools if tool.tool_kind is ToolKind.handoff
    })
    signal_turns = _escalation_signals(trace)
    stranded = verdict.label in (VerdictLabel.UNRESOLVED, VerdictLabel.ABANDONED)
    if handoff_turns:
        signaled = any(s <= handoff_turns[0] for s in signal_turns)
        passed = signaled
        rule = ("signal present at or before handoff" if signaled
                else "handoff with no escalation signal anywhere")
    else:
        passed = not (signal_turns and stranded)
        rule = ("signal present but caller stranded without escalation"
                if not passed else "no escalation needed, none attempted"
                if not signal_turns else "signal present, resolved without escalation")
    return QualityDimension(
        id="escalation_appropriateness",
        score=SCORE_PASS if passed else SCORE_FAIL,
        label="pass" if passed else "fail",
        tier="measured",
        evidence={
            "handoff_turns": handoff_turns,
            "signal_turns": signal_turns,
            "verdict_label": verdict.label.value,
            "rule": rule,
        },
        method="deterministic",
    )


def _barge_in_courtesy(priced: PricedTrace, verdict: Verdict) -> QualityDimension:
    """On barge-in turns with observable playback, the agent yielded.

    A barge turn counts as yielded when its playback was truncated by the
    barge-in; a turn whose playback ran to completion despite the barge flag
    counts as talked-over and fails the call. Turns with no playback spans
    are unobservable and excluded from the verdict (listed, not guessed).
    With no playback spans anywhere there is nothing to observe at all:
    ``instrumented`` / ``unmeasured`` -- the acoustic-absence pattern.
    """
    trace = priced.trace
    barge_turns = [t for t in trace.turns if t.barge_in]
    playbacks = [p for t in trace.turns for p in t.playback]
    if not playbacks:
        return QualityDimension(
            id="barge_in_courtesy",
            score=None,
            label="unmeasured",
            tier="instrumented",
            evidence={
                "reason": "no audio.playback spans: yielding is unobservable",
                "n_barge_turns": len(barge_turns),
                "rule": "yielded iff playback truncated_by barge_in",
            },
            method="deterministic",
        )
    talked_over = sorted({
        t.turn_index for t in barge_turns
        for p in t.playback if p.truncated_by is None
    })
    observable = sorted({
        t.turn_index for t in barge_turns if t.playback
    })
    unobservable = sorted({
        t.turn_index for t in barge_turns if not t.playback
    })
    passed = not talked_over
    return QualityDimension(
        id="barge_in_courtesy",
        score=SCORE_PASS if passed else SCORE_FAIL,
        label="pass" if passed else "fail",
        tier="measured",
        evidence={
            "n_barge_turns": len(barge_turns),
            "yielded_or_uninterrupted_turns": observable,
            "talked_over_turns": talked_over,
            "unobservable_turns": unobservable,
            "rule": "yielded iff playback truncated_by barge_in",
        },
        method="deterministic",
    )


def _reprompt_episode(trace) -> dict | None:
    """First adjacent same-slot ``slot_fill`` repeat (the D5 structural core:
    same ``decision_kind`` + same ``decision_chosen`` on adjacent turns)."""
    turns = trace.turns

    def slot_choice(turn):
        for span in turn.llm:
            if span.decision_kind is DecisionKind.slot_fill:
                return span
        return None

    for i in range(len(turns) - 1):
        first, second = slot_choice(turns[i]), slot_choice(turns[i + 1])
        if first is not None and second is not None \
                and first.decision_chosen == second.decision_chosen:
            return {"first_turn": turns[i].turn_index,
                    "reprompt_turn": turns[i + 1].turn_index,
                    "slot": second.decision_chosen}
    return None


def _thrash_repeats(trace) -> list[dict]:
    """Duplicate ``(tool_name, args_hash)`` repeats past the first occurrence
    (the D10 structural core)."""
    seen: set[tuple[str, str]] = set()
    repeats: list[dict] = []
    for turn in trace.turns:
        for tool in turn.tools:
            key = (tool.tool_name, tool.args_hash)
            if key in seen:
                repeats.append({"tool_name": tool.tool_name,
                                "turn_index": turn.turn_index,
                                "span_id": tool.span_id})
            else:
                seen.add(key)
    return repeats


def _non_repetition(priced: PricedTrace, verdict: Verdict) -> QualityDimension:
    """No reprompt loop, no duplicated tool work.

    Structural cores of D5/D10, re-checked here so the rubric needs no
    findings input -- agreement with ``detect()`` classes 5/10 is asserted
    by test on the golden fixtures, binding the two readings together.
    """
    trace = priced.trace
    reprompt = _reprompt_episode(trace)
    thrash = _thrash_repeats(trace)
    passed = reprompt is None and not thrash
    return QualityDimension(
        id="non_repetition",
        score=SCORE_PASS if passed else SCORE_FAIL,
        label="pass" if passed else "fail",
        tier="measured",
        evidence={
            "reprompt_episode": reprompt,
            "duplicate_tool_calls": thrash,
            "rule": "no adjacent same-slot slot_fill repeat; no duplicate (tool, args)",
        },
        method="deterministic",
    )


def _pending_dimension(dim_id: str) -> QualityDimension:
    """A declared model-judge dimension with no calibration: explicit no-op."""
    return QualityDimension(
        id=dim_id,
        score=None,
        label="pending",
        tier="not_measured",
        evidence={
            "reason": (
                "needs a calibrated model judge (>=60 hand labels, "
                "Cohen's kappa >= 0.75, ECE reported) behind "
                "TURNSTILE_ALLOW_PAID; none is registered"
            ),
            "rule": "no score without calibration (PRD 04 §3.2)",
        },
        method="judge_pending",
    )


def evaluate_quality(priced: PricedTrace, verdict: Verdict) -> QualityReport:
    """Score one priced, adjudicated call on the v1 rubric.

    Deterministic and $0: five rule-based dimensions over data the trace and
    verdict already carry, plus the pending judge dimensions as declared
    no-ops. Overall rolls up the SCORABLE dimensions only -- pending judges
    never feed it.
    """
    dimensions = [
        _task_success(priced, verdict),
        _slot_completeness(priced, verdict),
        _escalation_appropriateness(priced, verdict),
        _barge_in_courtesy(priced, verdict),
        _non_repetition(priced, verdict),
        *(_pending_dimension(dim_id) for dim_id in JUDGE_DIMENSIONS),
    ]
    scored = [d for d in dimensions if d.score is not None]
    measured = [d for d in scored if d.tier == "measured"]
    if any(d.label == "fail" for d in measured):
        overall_label = "fail"
    elif any(d.label == "partial" for d in measured):
        overall_label = "partial"
    else:
        overall_label = "pass"
    unmeasured = sorted(d.id for d in dimensions if d.label == "unmeasured")
    pending = sorted(d.id for d in dimensions if d.label == "pending")
    return QualityReport(
        dimensions=dimensions,
        overall=QualityOverall(
            label=overall_label,
            tier="measured" if measured else "instrumented",
        ),
        evidence=[
            {"scored_dimensions": len(scored), "of_total": len(dimensions)},
            {"unmeasured_dimensions": unmeasured},
            {"pending_dimensions": pending},
        ],
    )


def summarize_quality(overall_label: str, overall_tier: str, conv_cost_usd: float) -> str:
    """The beside-cost one-liner the dashboard/console shows, in one place so
    every surface pairs the same words: ``quality: <label> (<tier>) · ...``."""
    return (
        f"quality: {overall_label} ({overall_tier}) "
        f"\u00b7 cost ${conv_cost_usd:.2f}"
    )
