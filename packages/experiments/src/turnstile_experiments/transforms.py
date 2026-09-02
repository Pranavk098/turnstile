"""Deterministic trace transforms for the Section-A re-pricing remedies
(docs/superpowers/GLM-OVERNIGHT-BATCH.md, Section A).

Each remedy transforms the trace deterministically (fewer tokens / cheaper
rate / dropped spans); ``turnstile_experiments.repricing`` then re-prices the
transformed trace via ``turnstile_pricing.price_trace`` and reports
delta_cost = transformed - original -- the same rate-arbitrage shape
``model_routing`` uses on the replay path, but with no backend and no spend.

The registry is per VariantSpec FIELD: ``REPRICING_TRANSFORMS[field]`` maps to
``fn(trace, value) -> Trace`` where ``value`` is the field's VariantSpec value
(``True`` for a bool field, the policy string for e.g. ``context_strategy``).
A variant is re-pricing-executable iff EVERY field it sets has an entry here;
``repricing.run_repricing_matrix`` refuses anything else (fail loud, same
philosophy as ``guard``).

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

from turnstile_schema import Trace, VariantSpec
from turnstile_schema.spans import ToolCall

# VariantSpec field -> transform(trace, field_value) -> transformed trace.
# Pure functions: same trace + value in, same transformed trace out; no IO,
# no RNG, no backend.
REPRICING_TRANSFORMS: dict[str, Callable[[Trace, object], Trace]] = {}

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
def _transform_prefix_caching(trace: Trace, _value: object) -> Trace:
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


@_register("tool_batching")
def _transform_tool_batching(trace: Trace, _value: object) -> Trace:
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
    kept, _removed = _dedup_tool_calls(trace)
    return kept


@_register_unpriced("tool_batching")
def _unpriced_tool_batching(trace: Trace) -> float:
    """The deduped calls' vendor-reported cost (negative = saving) -- the
    only cost a removed ToolCall carries, and the only cost this remedy
    claims (see the transform's docstring for what is NOT claimed)."""
    _kept, removed = _dedup_tool_calls(trace)
    return -sum(tool.cost_usd for tool in removed)


_WINDOW_POLICY_RE = re.compile(r"^window:(\d+)$")


@_register("context_strategy")
def _transform_context_window(trace: Trace, value: object) -> Trace:
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

    # (turn_index, history_tokens) of every context-bearing turn, in order.
    history_by_turn: list[tuple[int, int]] = []
    new_turns = []
    any_changed = False
    for turn in trace.turns:
        context = turn.context
        if context is not None:
            history_by_turn.append((turn.turn_index, context.history_tokens))

        edge = None
        for turn_index, history in reversed(history_by_turn[:-1] if context is not None else history_by_turn):
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


def apply_variant_transform(trace: Trace, variant: VariantSpec) -> Trace:
    """Apply the re-pricing transform of every field ``variant`` sets, in
    VariantSpec field order, returning the transformed trace (the input is
    never mutated).

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
    for f in set_:
        trace = REPRICING_TRANSFORMS[f](trace, getattr(variant, f))
    return trace
