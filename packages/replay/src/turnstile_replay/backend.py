"""Injectable decision backend for pinned replay (PRD Sec.8.1).

`replay()`'s signature is frozen by PRD Sec.5 -- `replay(trace, variant,
from_turn) -> Trial`, no backend parameter -- so the backend that re-runs each
agent decision is wired in as a swappable module-level singleton, the same
pattern `packages/detectors` uses for its rate table (`_rates.get_rates()`):
a getter/setter pair, not a constructor argument.

    from turnstile_replay import set_backend, reset_backend, get_backend

    set_backend(my_backend)     # installs `my_backend` for all subsequent
                                 # replay()/experiment() calls in this process
    ...
    reset_backend()             # restore the Wave-1 MockBackend() default

A `DecisionBackend` is any callable
`(ReplayContext, LlmDecide, VariantSpec) -> ReplayedDecision`. `MockBackend`
below is the Wave-1 default -- deterministic, no live LLM/API call.

How a real OpenAI backend plugs in later: implement the SAME callable shape
-- render `ReplayContext.turns_before` (the pinned conversation history) plus
`original_span.decision_kind`/`variant` into a prompt, call the Chat
Completions/Responses API for whichever model `variant.model_routing` (or the
original span's model, if the variant doesn't touch this decision) selects,
and return a `ReplayedDecision` built from the API response (token usage from
the response's `usage` block, `output_text` from the message content,
`decision_chosen` from whatever the agent's own output-parsing does today).
Install it with `set_backend(OpenAIBackend(client))`. `replay()` itself never
changes -- it only ever calls `get_backend()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from turnstile_schema import VariantSpec
from turnstile_schema.spans import AsrTranscribe, LlmDecide
from turnstile_schema.trace import Turn


@dataclass(frozen=True)
class ReplayContext:
    """Everything a DecisionBackend gets besides the span being replayed and
    the variant: pinned conversation history up to (not including) the turn
    under replay, plus the CURRENT turn's caller-side ASR transcript(s)
    (`current_turn_asr`) -- the utterance the decision being replayed
    responds to. Caller side is fixed under pinned replay (PRD Sec.8.1 pins
    the caller side of EVERY turn), so both `turns_before` and
    `current_turn_asr` are always the ORIGINAL trace's spans, never
    regenerated: the counterfactual agent decides GIVEN the pinned caller
    audio, which is faithful replay, not leakage."""
    conversation_id: str
    scenario_id: str
    turn_index: int
    turns_before: tuple[Turn, ...]
    current_turn_asr: tuple[AsrTranscribe, ...] = ()


@dataclass(frozen=True)
class ReplayedDecision:
    """What a DecisionBackend returns for one re-run agent decision -- enough
    to rebuild the LlmDecide span and re-price it.

    M-2, documented at this boundary: `decision_chosen` is whatever the
    backend's own output parsing produced -- an UTTERANCE, not necessarily a
    parsed decision value. MockBackend echoes the original span's parsed
    value; OpenAIBackend currently passes the raw completion text through.
    Per-decision_kind parsing (escalate_check -> escalate/continue,
    tool_select -> tool name) is queued, not built, this wave."""
    model: str
    output_text: str
    decision_chosen: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0


class DecisionBackend(Protocol):
    def __call__(
        self, context: ReplayContext, original_span: LlmDecide, variant: VariantSpec
    ) -> ReplayedDecision: ...


# --------------------------------------------------------------------------- #
# MockBackend -- Wave-1 deterministic stand-in (PRD Sec.8, task brief). NO     #
# live LLM/API call.                                                           #
# --------------------------------------------------------------------------- #

# Model ids MockBackend treats as a known-safe cheaper reroute within the same
# family (both priced in pricing/rates.yaml): routing to one of these preserves
# output_text/decision_chosen exactly -- the "cheaper path, same outcome" case.
MOCK_SAFE_REROUTE_MODELS = frozenset({"gpt-5-mini", "gpt-5-nano"})


def _identity(span: LlmDecide) -> ReplayedDecision:
    return ReplayedDecision(
        model=span.gen_ai_request_model,
        output_text=span.output_text,
        decision_chosen=span.decision_chosen,
        input_tokens=span.input_tokens,
        output_tokens=span.output_tokens,
        cache_read_tokens=span.cache_read_tokens,
        cache_write_tokens=span.cache_write_tokens,
        reasoning_tokens=span.reasoning_tokens,
        latency_ms=span.latency_ms,
    )


def _same_outcome_reroute(span: LlmDecide, target_model: str) -> ReplayedDecision:
    d = _identity(span)
    return ReplayedDecision(
        model=target_model,
        output_text=d.output_text,
        decision_chosen=d.decision_chosen,
        input_tokens=d.input_tokens,
        output_tokens=d.output_tokens,
        cache_read_tokens=d.cache_read_tokens,
        cache_write_tokens=d.cache_write_tokens,
        reasoning_tokens=d.reasoning_tokens,
        latency_ms=d.latency_ms,
    )


def _divergent_reroute(span: LlmDecide, target_model: str) -> ReplayedDecision:
    """Deterministic stand-in for 'a different/untested model answers
    differently' -- exercises the divergence path (PRD Sec.8.1) without a
    live LLM. Reversing the original text plus a distinct marker keeps the
    difflib.SequenceMatcher ratio against the original low."""
    return ReplayedDecision(
        model=target_model,
        output_text=f"[mock-divergent:{target_model}]" + span.output_text[::-1],
        decision_chosen=f"__diverged__:{span.decision_chosen}",
        input_tokens=span.input_tokens,
        output_tokens=span.output_tokens,
        cache_read_tokens=span.cache_read_tokens,
        cache_write_tokens=span.cache_write_tokens,
        reasoning_tokens=span.reasoning_tokens,
        latency_ms=span.latency_ms,
    )


class MockBackend:
    """Deterministic Wave-1 DecisionBackend. No live LLM/API call.

    Rules, checked in order, driven entirely by
    `variant.model_routing.get(original_span.decision_kind.value)`:

    1. No entry for this span's decision_kind (or `model_routing` is None):
       identity replay -- the decision is returned unchanged. Every other
       VariantSpec knob (context_strategy, prefix_caching, retrieval_policy,
       tts_chunking, escalation_policy, tool_batching) is reserved for a
       future/real backend; MockBackend does not vary behavior on them in
       Wave 1.
    2. Entry routes to a `MOCK_SAFE_REROUTE_MODELS` model: same output_text/
       decision_chosen, cheaper model id -- re-pricing this under the new
       model's rate is what produces delta_cost < 0 with outcome_preserved
       (task acceptance case).
    3. Entry routes to any other model: treated as an untested reroute whose
       output cannot be assumed identical -- returns a deliberately different
       utterance, which is what exercises replay()'s divergence detection
       (task acceptance case).
    """

    def __call__(
        self, context: ReplayContext, original_span: LlmDecide, variant: VariantSpec
    ) -> ReplayedDecision:
        target_model = None
        if variant.model_routing:
            target_model = variant.model_routing.get(original_span.decision_kind.value)
        if target_model is None:
            return _identity(original_span)
        if target_model in MOCK_SAFE_REROUTE_MODELS:
            return _same_outcome_reroute(original_span, target_model)
        return _divergent_reroute(original_span, target_model)


_DEFAULT_BACKEND: DecisionBackend = MockBackend()
_current_backend: DecisionBackend = _DEFAULT_BACKEND


def get_backend() -> DecisionBackend:
    """The DecisionBackend replay()/experiment() use for subsequent calls."""
    return _current_backend


def set_backend(backend: DecisionBackend) -> None:
    """Install `backend` as the DecisionBackend for subsequent replay()/
    experiment() calls in this process. This is the injection point a real
    OpenAI backend (or a test double) uses -- replay() itself never changes."""
    global _current_backend
    _current_backend = backend


def reset_backend() -> None:
    """Restore the Wave-1 MockBackend() default."""
    global _current_backend
    _current_backend = _DEFAULT_BACKEND
