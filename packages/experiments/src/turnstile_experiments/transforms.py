"""Deterministic trace transforms for the Section-A re-pricing remedies
(docs/superpowers/GLM-OVERNIGHT-BATCH.md, Section A).

Each remedy transforms the priced trace deterministically (fewer tokens /
cheaper rate / dropped spans / truncated conversation); ``turnstile_experiments.
repricing`` then re-prices the transformed trace via
``turnstile_pricing.price_trace`` and reports delta_cost = transformed -
original -- the same rate-arbitrage shape ``model_routing`` uses on the replay
path, but with no backend and no spend.

The registry is per VariantSpec FIELD: ``REPRICING_TRANSFORMS[field]`` maps to
``fn(priced_trace, value) -> Trace`` where ``value`` is the field's VariantSpec
value (``True`` for a bool field, the policy string for e.g.
``context_strategy``). Transforms receive the PRICED trace because some
remedies read priced-conversation facts (the escalation cutoff reads the
verdict ``adjudicate`` computes -- which itself reads only ``trace.trace``,
costs unread). A variant is re-pricing-executable iff EVERY field it sets has
an entry here; ``repricing.run_repricing_matrix`` refuses anything else (fail
loud, same philosophy as ``guard``).

Honesty contract shared by every transform here: these transforms REDUCE or
re-rate work, so each saving is CONDITIONAL on the change preserving the
conversation's outcome -- unmeasurable on the synthetic corpus (H-1, no
preservation data). Every figure derived from a transform must carry
``repricing.CONDITIONAL_SAVINGS_LABEL`` ("deterministic conditional saving --
preservation unverified (Wave-2)") and must stay OUT of the gated
``proven_savings`` bucket (``margin.recoverable_margin(conditional=...)``
enforces the separate bucket).
"""
from __future__ import annotations

import re
from collections.abc import Callable

from turnstile_schema import PricedTrace, RateTable, Trace, VariantSpec, load_rates
from turnstile_schema.enums import VerdictLabel
from turnstile_schema.spans import ToolCall
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate

RATES_PATH = "pricing/rates.yaml"

# VariantSpec field -> transform(priced_trace, field_value) -> transformed
# trace. Pure functions: same input in, same transformed trace out; no IO, no
# RNG, no backend.
REPRICING_TRANSFORMS: dict[str, Callable[[PricedTrace, object], Trace]] = {}

# VariantSpec field -> unpriced_delta(trace) -> float. Some transforms remove
# cost that `price_trace` deliberately cannot see: ToolCall.cost_usd is
# vendor-reported metadata, excluded from span/stage costs so the stage-cost
# decomposition closes (packages/pricing). A field's entry here returns the
# NEGATIVE dollar cost of what the transform removes (a saving), on the
# ORIGINAL trace; `repricing.reprice_trace_delta` adds it to the re-priced
# conv_cost delta. Fields without an entry contribute 0.0.
UNPRICED_DELTAS: dict[str, Callable[[Trace], float]] = {}


def _register(field: str):
    def deco(fn):
        REPRICING_TRANSFORMS[field] = fn
        return fn
    return deco


def _register_unpriced(field: str):
    def deco(fn):
        UNPRICED_DELTAS[field] = fn
        return fn
    return deco


@_register("prefix_caching")
def _transform_prefix_caching(pt: PricedTrace, _value: object) -> Trace:
    """Re-price each decision's shared prefix at the ``cache_read`` rate
    (D2's remedy; the rate already exists in pricing/rates.yaml).

    Model (stated, deterministic): with append-only context, request i-1's
    full token count is the shared system+history prefix of request i, so
    under prompt caching those tokens bill at ``rate.cache_read`` instead of
    ``rate.input``. Per ``llm.decide`` span, in document order:

        new_cache_read = max(old_cache_read, min(prev_input, input_tokens))

    * the FIRST decision of a conversation gets no cache hit -- the cache is
      established BY it (honest default; ``cache_write_tokens`` is left
      untouched, which is also cost-neutral: rates.yaml prices cache_write
      at 0.0 -- OpenAI does not bill cache writes separately);
    * ``min(...)`` caps the shared prefix when context SHRANK between
      requests (pruning) -- exact under the corpus's monotonic context
      growth, an upper bound on the true shared prefix otherwise;
    * ``max(...)`` never REDUCES an existing cache hit.

    The prefix is re-billed, not removed: ``input_tokens`` (the workload) is
    unchanged, so the per-span delta is pure rate arbitrage,
    ``-prefix/1e6 * (rate.input - rate.cache_read)``, always <= 0.

    CONDITIONAL saving: bills the prefix at the cache rate, which matches
    real spend only if the deployment actually enables prompt caching and
    the provider's cache-hit conditions hold; that the outcome is preserved
    is NOT verified here (H-1). Report under the conditional label, never
    as a measured/proven saving.
    """
    trace = pt.trace
    new_turns = []
    prev_input = 0
    any_changed = False
    for turn in trace.turns:
        new_llm = []
        turn_changed = False
        for span in turn.llm:
            cache_read = max(span.cache_read_tokens, min(prev_input, span.input_tokens))
            if cache_read != span.cache_read_tokens:
                span = span.model_copy(update={"cache_read_tokens": cache_read})
                turn_changed = True
            new_llm.append(span)
            prev_input = span.input_tokens
        any_changed = any_changed or turn_changed
        new_turns.append(turn.model_copy(update={"llm": new_llm}) if turn_changed else turn)
    if not any_changed:
        return trace
    return trace.model_copy(update={"turns": new_turns})


_WINDOW_POLICY_RE = re.compile(r"^window:(\d+)$")


@_register("context_strategy")
def _transform_context_window(pt: PricedTrace, value: object) -> Trace:
    """Truncate each decision's input to the last N turns of history
    (``context_strategy="window:N"``, D2/D4's remedy). N is the policy,
    stated in the variant string itself (e.g. ``window:8``); any other
    policy string (e.g. ``summarize:2000``) has no transform yet and raises
    ``NotImplementedError`` -- never a silent identity.

    Model (corpus-native, stated): a decision's input is
    ``system_tokens + history_tokens + retrieved_tokens`` (the corpus's own
    ContextAssemble decomposition -- generate.py), and history accumulates
    per turn as (caller-utterance + agent-reply) tokens. Under window:N the
    decision at turn i keeps only turns (i-N, i]'s contributions, which --
    for an UNPRUNED trace -- is exactly

        new_input(i) = input(i) - history_tokens(turn j),  j = latest
        context-bearing turn with turn_index <= i - N;

    turns with fewer than N turns of history behind them are unchanged
    (nothing to truncate). For an ALREADY-PRUNED trace (the corpus also
    generates token-capped ``window``/``summarize`` contexts),
    ``history_tokens`` is the observed, possibly capped series, so the
    subtraction drops at most the observed level N turns back -- a LOWER
    BOUND on the true last-N-turns footprint, i.e. a conservative saving,
    stated here rather than guessed.

    Safety clamps (never bind on corpus traces, where H is nondecreasing):
    the reduced input is floored at system + retrieved tokens when the turn
    carries its own ContextAssemble (system + retrieval are always kept
    under the policy) -- a turn WITHOUT its own ContextAssemble is truncated
    with a 0 floor, since its decomposition cannot be verified there; and
    cache_read/cache_write are clamped to the reduced input (a cache hit
    cannot exceed the request size) so the PRD pricing formula can never see
    a negative full-rate term.

    CONDITIONAL saving: truncation preserves the outcome only if the dropped
    history was not needed for it -- unmeasurable on the synthetic corpus
    (H-1); report under the conditional label, never as measured.
    """
    match = _WINDOW_POLICY_RE.match(str(value))
    if not match:
        raise NotImplementedError(
            f"context_strategy={value!r} has no deterministic re-pricing "
            f"transform yet (implemented policies: window:<N>)."
        )
    n_turns = int(match.group(1))
    if n_turns < 1:
        raise NotImplementedError(f"context_strategy={value!r}: window must keep >= 1 turn")

    trace = pt.trace
    # (turn_index, history_tokens) of every context-bearing turn, in order.
    history_by_turn: list[tuple[int, int]] = []
    new_turns = []
    any_changed = False
    for turn in trace.turns:
        context = turn.context
        if context is not None:
            history_by_turn.append((turn.turn_index, context.history_tokens))

        edge = None
        seen_all = history_by_turn[:-1] if context is not None else history_by_turn
        for turn_index, history in reversed(seen_all):
            if turn_index <= turn.turn_index - n_turns:
                edge = history
                break

        if edge is None or not turn.llm:
            new_turns.append(turn)
            continue

        floor = 0
        if context is not None:
            floor = context.system_tokens + context.retrieved_tokens
        new_llm = []
        turn_changed = False
        for span in turn.llm:
            new_input = max(span.input_tokens - edge, floor)
            if new_input != span.input_tokens:
                span = span.model_copy(update={
                    "input_tokens": new_input,
                    "cache_read_tokens": min(span.cache_read_tokens, new_input),
                    "cache_write_tokens": min(span.cache_write_tokens, new_input),
                })
                turn_changed = True
            new_llm.append(span)
        any_changed = any_changed or turn_changed
        new_turns.append(turn.model_copy(update={"llm": new_llm}) if turn_changed else turn)

    if not any_changed:
        return trace
    return trace.model_copy(update={"turns": new_turns})


@_register("tool_batching")
def _transform_tool_batching(pt: PricedTrace, _value: object) -> Trace:
    """Collapse duplicate tool calls to one billed call (D10's remedy).

    Duplicate rule (verbatim D10's detection rule -- reused, not reinvented):
    the FIRST occurrence of a ``(tool_name, args_hash)`` pair in the
    conversation is the legitimate call; every later occurrence is dropped
    from the trace. This collapses cross-turn repeats (the corpus's and golden
    fixture 10's shape: a redundant re-call in a later turn) and within-turn
    duplicates alike.

    What is deterministically saved -- and what is NOT: dropping the duplicate
    span removes only the redundant EXECUTION (the vendor call). The
    duplicate's turn still happens under a memoizing tool layer -- the caller
    still speaks, the agent's ``llm.decide`` still runs -- so this remedy
    does NOT claim the redundant turn's cost. That turn-level attribution
    ("cost of the duplicate calls + their turns") remains Detector 10's
    Tier-2 waste estimate, deliberately NOT claimed here; this remedy claims
    only "the deduped calls' cost" (vendor-reported ``cost_usd``, via
    ``UNPRICED_DELTAS`` -- ``price_trace`` excludes tool spans by design).

    CONDITIONAL saving + honest zero: batching preserves the outcome only if
    the duplicate is truly redundant (same args -> same result; fixture 10's
    own builder comment: both calls actually succeeded) -- preservation is
    unverified (H-1), report under the conditional label. And the synthetic
    corpus records no vendor cost (``cost_usd`` defaults to 0.0 and neither
    the generator nor fixture 10 sets it), so on THIS corpus the delta is
    exactly 0.0 -- the redundancy's measured cost on the corpus is turn-level
    (D10's Tier-2 number), not vendor-level. That zero is honest: do not
    turn it into the turn-level figure by stealth.
    """
    kept, _removed = _dedup_tool_calls(pt.trace)
    return kept


@_register_unpriced("tool_batching")
def _unpriced_tool_batching(trace: Trace) -> float:
    """The deduped calls' vendor-reported cost (negative = saving) -- the
    only cost a removed ToolCall carries, and the only cost this remedy
    claims (see the transform's docstring for what is NOT claimed)."""
    _kept, removed = _dedup_tool_calls(trace)
    return -sum(tool.cost_usd for tool in removed)


_ESCALATION_POLICY_RE = re.compile(r"^threshold:(\d+(?:\.\d+)?)$")


@_register("escalation_policy")
def _transform_escalation_early_cutoff(pt: PricedTrace, value: object) -> Trace:
    """Truncate the conversation at the earliest predictable-escalation turn
    (``escalation_policy="threshold:0.85"``, D9 Tier-1's remedy).

    The cutoff is D9's own, already-computed quantity (the batch doc: "reuse
    what is already computed"): ``adjudicate(pt).turn_of_no_return`` -- the
    Wave-1 deterministic stand-in for a live escalation classifier (earliest
    ``escalate_check`` turn, handoff-turn fallback; see d09's STAND-IN note).
    Applied only when the verdict is ``ESCALATED`` and the cutoff exists and
    is not already the last turn; every other trace is left UNCHANGED
    (delta 0 -- honestly: there is no predictable-early cutoff to act on).

    Model (stated, deterministic): under the policy the agent escalates at
    turn t instead of stalling, so the conversation ENDS at t: turns with
    ``turn_index > t`` are removed entirely (caller utterances included --
    the call is over), and turn t itself still happens (it becomes the
    escalation turn). Delta = the cost of the turns AFTER t -- note this is
    turns t+1..end, one turn narrower than D9's inclusive Tier-1 waste
    ("full cost of turns t..end"): the detector's debt includes the
    escalation turn, the remedy's saving cannot (the escalation still runs).

    Telephony: the conversation-level leg is a corpus fact of the WHOLE call
    (billable_seconds = max(1, round(total wall seconds)) in generate.py).
    Under the shorter call it shrinks pro-rata by wall time --
    ``billable * kept_wall / total_wall`` -- the same pro-rata model
    ``price_trace`` uses to attribute telephony to turns; kept_wall/total_wall
    is exact for the corpus (turn windows tile the call from 0). A trace
    with zero total wall duration keeps its telephony unchanged (cannot
    attribute; conservative).

    D9 Tier-2 (rejected terminal handoff, verdict UNRESOLVED) is deliberately
    NOT covered: "the whole call was wasted" is not implementable as a
    preservation-plausible transform (the call never escalated). The
    detector's Tier-2 number stands as Tier-2.

    CONDITIONAL saving: the caller's outcome (escalation reached) is
    preserved only if the agent escalating at t would have produced the same
    resolution -- unmeasurable on the synthetic corpus (H-1); report under
    the conditional label, never as measured.
    """
    if not _ESCALATION_POLICY_RE.match(str(value)):
        raise NotImplementedError(
            f"escalation_policy={value!r} has no deterministic re-pricing "
            f"transform yet (implemented policies: threshold:<p>)."
        )
    trace = pt.trace
    verdict = adjudicate(pt)
    if verdict.label is not VerdictLabel.ESCALATED:
        return trace
    t = verdict.turn_of_no_return
    if t is None:
        return trace
    t_pos = next((i for i, turn in enumerate(trace.turns) if turn.turn_index == t), None)
    if t_pos is None or t_pos >= len(trace.turns) - 1:
        return trace  # nothing runs after the cutoff: no saving to claim

    kept_turns = trace.turns[:t_pos + 1]
    new_turns = list(kept_turns)
    telephony = trace.telephony
    if telephony is not None:
        total_wall_ms = sum(tu.wall_end_ms - tu.wall_start_ms for tu in trace.turns)
        kept_wall_ms = sum(tu.wall_end_ms - tu.wall_start_ms for tu in kept_turns)
        if total_wall_ms > 0:
            new_billable = max(0, round(telephony.billable_seconds * kept_wall_ms / total_wall_ms))
            if new_billable != telephony.billable_seconds:
                telephony = telephony.model_copy(update={"billable_seconds": new_billable})
    new_trace = trace.model_copy(update={"turns": new_turns, "telephony": telephony})
    return new_trace


def _dedup_tool_calls(trace: Trace) -> tuple[Trace, list[ToolCall]]:
    """D10's duplicate rule, shared by the transform (which drops the
    duplicates) and the unpriced-delta hook (which costs them): walk turns in
    order; the first ``(tool_name, args_hash)`` occurrence is kept, every
    later one is removed. Returns (new trace, removed spans, in removal
    order). Pure: never mutates the input."""
    seen: set[tuple[str, str]] = set()
    removed: list[ToolCall] = []
    new_turns = []
    any_changed = False
    for turn in trace.turns:
        new_tools = []
        turn_changed = False
        for tool in turn.tools:
            key = (tool.tool_name, tool.args_hash)
            if key in seen:
                removed.append(tool)
                turn_changed = True
                continue
            seen.add(key)
            new_tools.append(tool)
        any_changed = any_changed or turn_changed
        new_turns.append(turn.model_copy(update={"tools": new_tools}) if turn_changed else turn)
    if not any_changed:
        return trace, removed
    return trace.model_copy(update={"turns": new_turns}), removed


def apply_variant_transform(
    pt: PricedTrace, variant: VariantSpec, rates: RateTable | None = None
) -> Trace:
    """Apply the re-pricing transform of every field ``variant`` sets, in
    VariantSpec field order, returning the transformed trace (the input is
    never mutated).

    Each transform receives a PRICED trace. The first field reuses ``pt``
    (already priced); a later field in a multi-field variant prices the
    intermediate trace first (``rates`` defaults to the repo's
    ``pricing/rates.yaml``) so chained remedies compose deterministically.

    Raises ``NotImplementedError`` if the variant sets a field with no
    transform (nothing silently replays as a no-op) or no fields at all."""
    set_ = [f for f in VariantSpec.model_fields if getattr(variant, f) is not None]
    if not set_:
        raise NotImplementedError(
            "variant sets no fields at all -- an identity transform is a "
            "no-op, not a measurement."
        )
    missing = [f for f in set_ if f not in REPRICING_TRANSFORMS]
    if missing:
        raise NotImplementedError(
            f"no deterministic re-pricing transform for field(s) {missing}: "
            f"implement it in turnstile_experiments.transforms first "
            f"(fields with a transform: {sorted(REPRICING_TRANSFORMS)})."
        )
    rates = rates if rates is not None else load_rates(RATES_PATH)
    trace = pt.trace
    priced = pt
    for idx, f in enumerate(set_):
        if idx > 0:
            priced = price_trace(trace, rates)
        trace = REPRICING_TRANSFORMS[f](priced, getattr(variant, f))
    return trace
