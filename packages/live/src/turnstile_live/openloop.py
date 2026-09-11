"""Open-loop preservation harness (Phase 3): run the cheaper model forward to a
terminal state and watch the verdict hold or fail.

Per scripted conversation two paths run on the SAME caller texts: the
baseline (P1 mock policy) and the live policy (mock in tests, the capped LLM
in the paid run). Divergent = decision paths differ. Divergent live paths are
judged under BOTH rules, reported side by side, never folded:

- rule 1 (registry-grounded, deterministic): the scenario's registry-required
  tool committed AND the executed verdict RESOLVED -> True; registered but
  not -> False; lookup intent (no requirement) or unregistered -> None;
- rule 2 (LLM judge, paid): a small model reads the final transcript.

Mock tools respond (their registered effects already commit the required
tools when selected -- see turnstile_live.tools); NOTHING here estimates or
simulates tool outcomes. Paid spend is bounded by enforce_budget (worst-case
tokens x mini rates, judges bounded by conversation count).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from turnstile_ingest.adapter import load
from turnstile_ingest.model import (
    IngestAsr,
    IngestCall,
    IngestLlm,
    IngestTelephony,
    IngestTool,
    IngestTts,
    IngestTurn,
)
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate
from turnstile_verdict.registry import lookup

from turnstile_live import loop as text_loop
from turnstile_live.policy import decide as mock_decide
from turnstile_live.tools import run_tool as run_mock_tool
from turnstile_live.voice import LlmDecision

BUDGET_CAP_USD = 2.0

# Worst-case paid call: 4000 input + 1000 output tokens at gpt-5-mini rates
# ($0.25 / $2.00 per M). Deliberately pessimistic; real calls are ~10x smaller.
_WORST_CASE_USD_PER_CALL = 4000 / 1e6 * 0.25 + 1000 / 1e6 * 2.00

_CALL_EPOCH = datetime(2026, 9, 11, 9, 0, 0, tzinfo=timezone.utc)

_LLM_MODEL = "gpt-5-mini"  # label only; real model id rides the paid policy


@dataclass(frozen=True)
class ScriptedConversation:
    """One authored probe: fixed caller texts, open-looped by both policies."""

    id: str
    scenario: str
    caller_texts: tuple[str, ...]


def _scripts(scenario: str, opens: str, detail: str) -> list[ScriptedConversation]:
    """Four compact variants per scenario: cooperative / terse /
    human-request / confirm-first. Turn 3 always closes (terminal state)."""
    return [
        ScriptedConversation(f"{scenario}-v1", scenario, (opens, detail, "Thanks, that is all. Bye!")),
        ScriptedConversation(f"{scenario}-v2", scenario, (opens.split(",")[0] + ".", detail, "Ok bye.")),
        ScriptedConversation(f"{scenario}-v3", scenario, (opens, "Let me talk to a human.", "Thanks, that is all. Bye!")),
        ScriptedConversation(f"{scenario}-v4", scenario, (f"{opens} {detail}", "Yes, that is right.", "Thanks, that is all. Bye!")),
    ]


SCRIPT_SET: tuple[ScriptedConversation, ...] = tuple(
    conv
    for scenario, opens, detail in (
        ("order_status", "Hi, where is my order?", "It is order ORD-4481, supposed to arrive Thursday."),
        ("tech_support", "Hi, my wifi keeps dropping.", "The router is a HomeHub 3000, it drops every evening."),
        ("refund", "Hi, I want a refund for order ORD-2207.", "It was $42.50, charged last Tuesday."),
        ("billing_dispute", "Hi, I was charged twice on my bill.", "The August bill shows two identical charges."),
        ("cancel_subscription", "Hi, I want to cancel my subscription.", "The plan renews on the first, cancel before then."),
        ("appointment_reschedule", "Hi, I need to move my Tuesday appointment.", "Any afternoon next week works for me."),
    )
    for conv in _scripts(scenario, opens, detail)
)


def _extra_scripts(scenario: str, short_open: str, alt_detail: str) -> list[ScriptedConversation]:
    """Phase-5 extension probes (v5/v6): alternate openings/details and a
    warmer close. SCRIPT_SET stays frozen (P3's gate pins its length)."""
    return [
        ScriptedConversation(f"{scenario}-v5", scenario, (short_open, alt_detail, "Great, goodbye!")),
        ScriptedConversation(f"{scenario}-v6", scenario, (short_open, alt_detail, "Perfect, thanks so much. Bye!")),
    ]


EXTRA_SCRIPTS: tuple[ScriptedConversation, ...] = tuple(
    conv
    for scenario, short_open, alt_detail in (
        ("order_status", "Order status?", "ORD-4481, due Thursday."),
        ("tech_support", "Internet down again.", "HomeHub 3000, red light."),
        ("refund", "Refund, please.", "ORD-2207, $42.50."),
        ("billing_dispute", "Double charge?", "August bill, twice."),
        ("cancel_subscription", "Cancel, please.", "Renews on the first."),
        ("appointment_reschedule", "Move my appointment?", "Tuesday, afternoon works."),
    )
    for conv in _extra_scripts(scenario, short_open, alt_detail)
)


@dataclass(frozen=True)
class BaselinePath:
    decisions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ExecutedTurn:
    decision_kind: str
    decision: str
    reply: str
    tools: tuple[tuple[str, str], ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ExecutedConversation:
    id: str
    scenario: str
    turns: tuple[ExecutedTurn, ...]
    verdict_label: str

    def decision_path(self) -> tuple[tuple[str, str], ...]:
        return tuple((t.decision_kind, t.decision) for t in self.turns)

    def divergent_from(self, baseline: BaselinePath) -> bool:
        return self.decision_path() != baseline.decisions


def run_baseline(conv: ScriptedConversation) -> BaselinePath:
    """The pinned baseline: P1 mock policy decisions on the scripted texts."""
    return BaselinePath(decisions=tuple(
        (a.decision_kind, a.decision)
        for a in (mock_decide(conv.scenario, text, i) for i, text in enumerate(conv.caller_texts))
    ))


def candidates_for(scenario: str, turn_index: int) -> tuple[str, ...]:
    """Labels the live model may pick on this turn. Turn 0 is the route
    universe; later turns offer the baseline's reachable action labels
    (lookup/close/escalate/inform) PLUS the scenario's registry-required
    terminal tool when it has one. Offering less would force divergence and
    make preservation unmeasurable, so the offered set is a superset of the
    baseline's reach -- documented, not tuned per run."""
    from turnstile_live.voice import ROUTE_CANDIDATES

    if turn_index == 0:
        return ROUTE_CANDIDATES
    labels = ["lookup_invoices", "close_call", "escalate", "inform"]
    spec = lookup(scenario)
    if spec is not None and spec.requires_mutation is not None:
        required = spec.requires_mutation
        if required not in labels:
            labels.insert(1, required)
    return tuple(labels)


def tools_for(decision_kind: str, decision: str) -> list:
    """Executed tool records for one decision: the selected mock tool on
    tool_select, the committed handoff on escalate, nothing otherwise.
    Shared single source with the barge-in loop (same package)."""
    if decision_kind == "tool_select":
        result = run_mock_tool(decision, {})
        return [result]
    if decision_kind == "escalate_check" and decision == "escalate":
        return [run_mock_tool("transfer_to_agent", {})]
    return []


def _emit_call(conv: ScriptedConversation, decisions: list[LlmDecision]) -> IngestCall:
    """Emit the executed decisions as an ingest call (P1 text-loop layout:
    fixed virtual-clock slots, text-only TTS)."""
    turns: list[IngestTurn] = []
    for index, (text, action) in enumerate(zip(conv.caller_texts, decisions)):
        base = index * (text_loop.TURN_SLOT_MS + text_loop.TURN_GAP_MS)
        # SAME tool records the rule judges (single source: _tools_for).
        tool_entries = [
            IngestTool(
                name=result.name, kind=result.kind, effect=result.effect,
                args=result.args,
            )
            for result in tools_for(action.decision_kind, action.decision)
        ]
        turns.append(IngestTurn(
            start_ms=base, end_ms=base + text_loop.TURN_SLOT_MS,
            asr=IngestAsr(
                transcript=text, start_ms=base + text_loop.ASR_START_MS,
                duration_ms=text_loop.ASR_DURATION_MS,
            ),
            llm=IngestLlm(
                model=_LLM_MODEL, input_tokens=action.input_tokens,
                output_tokens=action.output_tokens,
                decision_kind=action.decision_kind, decision=action.decision,
                output_text=action.reply,
                start_ms=base + text_loop.LLM_START_MS,
                duration_ms=text_loop.LLM_DURATION_MS,
                decision_candidates=[action.decision],
            ),
            tts=IngestTts(
                text=action.reply, start_ms=base + text_loop.TTS_START_MS,
                duration_ms=text_loop.TTS_DURATION_MS,
            ),
            tools=tool_entries,
        ))
    call_end_ms = turns[-1].end_ms
    return IngestCall(
        id=conv.id, scenario=conv.scenario,
        started=_CALL_EPOCH,
        ended=_CALL_EPOCH + timedelta(milliseconds=call_end_ms),
        end_reason="caller_hangup",
        agent_version="turnstile-live openloop@mock-1",
        telephony=IngestTelephony(billable_seconds=(call_end_ms + 999) // 1000),
        turns=turns,
    )


def run_live(conv: ScriptedConversation, policy, rates) -> tuple[ExecutedConversation, IngestCall]:
    """Drive one conversation open-loop through `policy` (anything with
    .decide(scenario, transcript, turn_index, candidates)); adjudicate the
    executed trace for real. Returns (executed, ingest_call)."""
    decisions = [policy.decide(conv.scenario, text, i, candidates_for(conv.scenario, i))
                 for i, text in enumerate(conv.caller_texts)]
    call = _emit_call(conv, decisions)
    verdict = adjudicate(price_trace(load(call, rates=rates), rates))
    executed = ExecutedConversation(
        id=conv.id, scenario=conv.scenario,
        turns=tuple(
            ExecutedTurn(
                decision_kind=d.decision_kind, decision=d.decision, reply=d.reply,
                tools=tuple(
                    (r.name, r.effect) for r in tools_for(d.decision_kind, d.decision)
                ),
                input_tokens=d.input_tokens, output_tokens=d.output_tokens,
            )
            for d in decisions
        ),
        verdict_label=verdict.label.value,
    )
    return executed, call


def rule1_registry(
    scenario: str, tools: list[tuple[str, str]], verdict_label: str
) -> bool | None:
    """Registry-grounded resolution: True iff the registry-required tool
    committed on the executed path AND the executed verdict is RESOLVED.
    Lookup intents (no requirement) and unregistered scenarios -> None."""
    spec = lookup(scenario)
    if spec is None or spec.requires_mutation is None:
        return None
    committed = any(name == spec.requires_mutation and effect == "committed"
                    for name, effect in tools)
    return True if (committed and verdict_label == "RESOLVED") else False


JUDGE_SYSTEM = (
    "You judge whether a support call resolved the caller's issue. "
    "Read the transcript, then reply with exactly one word: "
    "RESOLVED or UNRESOLVED."
)


def rule2_judge(call_chat, scenario: str, transcript: str) -> tuple[bool | None, int, int]:
    """LLM-judge resolution: (verdict, input_tokens, output_tokens). Garbage
    (anything but exactly RESOLVED/UNRESOLVED) -> None, listed separately."""
    text, in_tok, out_tok = call_chat([
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": f"Caller intent: {scenario}\n\nTranscript:\n{transcript}"},
    ])
    word = text.strip().upper()
    if word == "RESOLVED":
        return True, in_tok, out_tok
    if word == "UNRESOLVED":
        return False, in_tok, out_tok
    return None, in_tok, out_tok


def openai_judge_chat(model: str):
    """Real judge chat callable (paid; construct only behind the paid gate)."""
    from openai import OpenAI

    client = OpenAI()

    def call(messages: list[dict]) -> tuple[str, int, int]:
        response = client.chat.completions.create(
            model=model, messages=messages, timeout=60.0)
        usage = response.usage
        return (response.choices[0].message.content or "",
                usage.prompt_tokens, usage.completion_tokens)

    return call


def estimate_worst_case_usd(n_convos: int, turns_each: int) -> float:
    """Pessimistic spend bound: every decision + one judge per conversation
    at worst-case tokens. Judges are bounded by conversation count (only
    divergent conversations are judged, and divergent <= all)."""
    return (n_convos * turns_each + n_convos) * _WORST_CASE_USD_PER_CALL


def enforce_budget(n_convos: int, turns_each: int, cap_usd: float = BUDGET_CAP_USD) -> float:
    """Refuse (RuntimeError) when the worst-case estimate exceeds the cap."""
    estimate = estimate_worst_case_usd(n_convos, turns_each)
    if estimate > cap_usd:
        raise RuntimeError(
            f"open-loop run refuses: worst-case estimate ${estimate:.2f} "
            f"exceeds the ${cap_usd:.2f} budget cap."
        )
    return estimate


def summarize(rows: list[dict]) -> dict:
    """Collapse per-conversation rows to the two SEPARATE measured figures.

    Registry denominator: divergent rows with rule1 True/False (None
    excluded, counted as n_undecidable). Judge denominator: divergent rows
    with rule2 True/False (unparsed excluded, counted as n_judge_unparsed).
    Never folded into each other, into identity, or into modeled -- the
    returned keys carry no such figure."""
    divergent = [r for r in rows if r["divergent"]]
    reg_decided = [r for r in divergent if r["rule1"] is not None]
    judge_decided = [r for r in divergent if r["rule2"] is not None]
    return {
        "n_conversations": len(rows),
        "n_divergent": len(divergent),
        "n_undecidable": sum(1 for r in divergent if r["rule1"] is None),
        "n_judge_unparsed": sum(1 for r in divergent if r["rule2"] is None),
        "registry": (
            sum(1 for r in reg_decided if r["rule1"]) / len(reg_decided)
            if reg_decided else None
        ),
        "llm_judge": (
            sum(1 for r in judge_decided if r["rule2"]) / len(judge_decided)
            if judge_decided else None
        ),
    }
