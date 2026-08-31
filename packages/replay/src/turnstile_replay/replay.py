"""Counterfactual replay engine (PRD Sec.5, Sec.8) -- the credibility core.

Pinned replay (PRD Sec.8.1, baseline, must ship): the caller side (asr / vad /
context / tts / playback spans) is fixed from the original trace for every
turn. Tool responses are served from the trace's own args_hash-keyed cache
(Wave-1 MockBackend never proposes a different tool_select decision, so this
is always a cache hit against the tool's own original entry -- see
`_tool_cache` below). Only the AGENT's `llm.decide` spans from `from_turn`
onward are re-run, through an injectable `DecisionBackend`
(`turnstile_replay.backend`), under the variant policy. The rebuilt trace is
re-priced (`turnstile_pricing.price_trace`) and re-adjudicated
(`turnstile_verdict.adjudicate`) to produce a `Trial`.

Divergence (PRD Sec.8.1): the FIRST replayed decision at or after `from_turn`
(the "pivot" -- PRD Sec.8.1's "utterance at turn k") is compared to the
original via `difflib.SequenceMatcher.ratio()` on `output_text`, the
documented Wave-1 proxy for semantic similarity (no embedding model this
wave). Below `DIVERGENCE_SIMILARITY_THRESHOLD` the pinned caller audio is no
longer a valid continuation ("the conversation has forked") -- the trial is
marked `status="divergent"` and is NOT re-priced (`delta_cost`,
`delta_latency_ms`, `outcome_preserved` are all `None`). Wave 1 has no
open-loop fallback (PRD Sec.8.1's stretch mode), so divergent trials stay
`"divergent"` rather than becoming `"excluded"` -- `aggregate_experiment`
counts them toward `n` and lists them in `divergent_exemplars`, which is how
the exclusion/fork rate gets reported honestly (PRD Sec.8.3) instead of
hidden.

`status="excluded"` is reserved for trials that could not be attempted at
all: `from_turn` at or past the end of the trace, or no `llm.decide` span
exists at or after it -- there is nothing for the variant to act on.
"""
from __future__ import annotations

import difflib

from turnstile_schema import ExperimentResult, PricedTrace, Trial, VariantSpec
from turnstile_schema.spans import LlmDecide, ToolCall
from turnstile_schema.trace import Trace, Turn
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate
from turnstile_stats import aggregate_experiment

from turnstile_replay._rates import get_rates
from turnstile_replay.backend import ReplayContext, ReplayedDecision, get_backend

# PRD Sec.8.1, verbatim: "if the variant agent's utterance at turn k has
# semantic similarity < 0.75 to the original, the conversation has forked."
DIVERGENCE_SIMILARITY_THRESHOLD = 0.75


def _similarity(a: str, b: str) -> float:
    """Wave-1 documented proxy for semantic similarity: difflib.SequenceMatcher
    ratio on output_text (PRD Sec.8.1 / task brief -- no embedding model this
    wave)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _llm_spans_from(trace: Trace, from_turn: int) -> list[tuple[int, LlmDecide]]:
    """(turn_index, span) for every llm.decide span at turn_index >= from_turn,
    in document order."""
    out: list[tuple[int, LlmDecide]] = []
    for turn in trace.turns:
        if turn.turn_index < from_turn:
            continue
        for span in turn.llm:
            out.append((turn.turn_index, span))
    return out


def _tool_cache(trace: Trace) -> dict[str, ToolCall]:
    """args_hash -> ToolCall, pooled across the whole trace. Pinned replay
    (PRD Sec.8.1) serves tool responses from this cache; Wave-1 MockBackend
    never changes a tool_select decision, so every lookup below hits the
    tool's own original entry. A future backend that DOES propose different
    tool args would see a cache miss here -- the fixed caller audio has no
    live response for that hash. That should be treated as another
    divergence trigger; no Wave-1 backend produces that case, so it is
    documented but not implemented."""
    cache: dict[str, ToolCall] = {}
    for turn in trace.turns:
        for tool in turn.tools:
            cache[tool.args_hash] = tool
    return cache


def _rebuild_llm_span(original: LlmDecide, decision: ReplayedDecision) -> LlmDecide:
    return original.model_copy(update={
        "gen_ai_request_model": decision.model,
        "output_text": decision.output_text,
        "decision_chosen": decision.decision_chosen,
        "input_tokens": decision.input_tokens,
        "output_tokens": decision.output_tokens,
        "cache_read_tokens": decision.cache_read_tokens,
        "cache_write_tokens": decision.cache_write_tokens,
        "reasoning_tokens": decision.reasoning_tokens,
        "latency_ms": decision.latency_ms,
    })


def replay(trace: PricedTrace, variant: VariantSpec, from_turn: int) -> Trial:
    """Pinned replay of `trace` under `variant` from turn `from_turn` (PRD
    Sec.5 / Sec.8.1)."""
    conv = trace.trace
    trace_id = conv.conversation.conversation_id

    targets = _llm_spans_from(conv, from_turn)
    if not targets:
        return Trial(trace_id=trace_id, status="excluded",
                     delta_cost=None, delta_latency_ms=None, outcome_preserved=None)

    backend = get_backend()
    replaced: dict[str, ReplayedDecision] = {}
    for turn_idx, span in targets:
        context = ReplayContext(
            conversation_id=conv.conversation.conversation_id,
            scenario_id=conv.conversation.scenario_id,
            turn_index=turn_idx,
            turns_before=tuple(t for t in conv.turns if t.turn_index < turn_idx),
        )
        replaced[span.span_id] = backend(context, span, variant)

    # -- Divergence gate: the pivot is the FIRST replayed decision at/after
    #    from_turn (PRD Sec.8.1's "utterance at turn k"). ---------------------
    _pivot_turn_idx, pivot_span = targets[0]
    pivot_decision = replaced[pivot_span.span_id]
    similarity = _similarity(pivot_span.output_text, pivot_decision.output_text)
    if similarity < DIVERGENCE_SIMILARITY_THRESHOLD:
        return Trial(trace_id=trace_id, status="divergent",
                     delta_cost=None, delta_latency_ms=None, outcome_preserved=None)

    # -- Rebuild the trace: turns before from_turn are pinned verbatim; turns
    #    at/after it get their llm.decide spans replaced and their tool spans
    #    re-served from the args_hash cache (see _tool_cache). ---------------
    tool_cache = _tool_cache(conv)
    new_turns: list[Turn] = []
    for turn in conv.turns:
        if turn.turn_index < from_turn or not turn.llm:
            new_turns.append(turn)
            continue
        new_llm = [_rebuild_llm_span(s, replaced[s.span_id]) for s in turn.llm]
        new_tools = [tool_cache.get(t.args_hash, t) for t in turn.tools]
        new_turns.append(turn.model_copy(update={"llm": new_llm, "tools": new_tools}))
    new_trace = conv.model_copy(update={"turns": new_turns})

    rates = get_rates()
    new_priced = price_trace(new_trace, rates)

    original_verdict = adjudicate(trace)
    new_verdict = adjudicate(new_priced)

    delta_cost = new_priced.conv_cost - trace.conv_cost
    original_latency = sum(s.latency_ms for _, s in targets)
    replayed_latency = sum(d.latency_ms for d in replaced.values())
    delta_latency_ms = float(replayed_latency - original_latency)

    return Trial(
        trace_id=trace_id,
        status="ok",
        delta_cost=delta_cost,
        delta_latency_ms=delta_latency_ms,
        outcome_preserved=(new_verdict.label == original_verdict.label),
    )


def _earliest_applicable_turn(trace: PricedTrace, variant: VariantSpec) -> int:
    """The earliest turn_index `variant` applies to, for experiment()'s
    per-trace `from_turn` (PRD Sec.5's `experiment(traces, variant)`).

    Wave 1: `model_routing` is the only VariantSpec knob MockBackend
    differentiates on (see backend.py's docstring), so this is the first turn
    with an llm.decide span whose decision_kind is a model_routing key.
      * No match anywhere in the trace -> returns `len(trace.turns)`, which
        replay() resolves to `status="excluded"` (nothing to act on).
      * `variant.model_routing` unset -> returns 0 (replay the whole trace;
        MockBackend identity-replays every span, a legitimate zero-delta
        trial for a variant that doesn't touch this knob).
    """
    if variant.model_routing:
        kinds = set(variant.model_routing.keys())
        for turn in trace.trace.turns:
            for span in turn.llm:
                if span.decision_kind.value in kinds:
                    return turn.turn_index
        return len(trace.trace.turns)
    return 0


def experiment(traces: list[PricedTrace], variant: VariantSpec) -> ExperimentResult:
    """Replay every trace under `variant`, aggregate via
    `turnstile_stats.aggregate_experiment` (PRD Sec.5 / Sec.8.3)."""
    trials = [replay(t, variant, _earliest_applicable_turn(t, variant)) for t in traces]
    return aggregate_experiment(trials)
