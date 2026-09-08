"""``OpenAIBackend`` -- the real (paid) ``DecisionBackend`` (docs/CORPUS.md
"Real replay backend"). Implements the SAME callable shape
``turnstile_replay.backend`` documents for a real backend: render
``ReplayContext.turns_before`` (the pinned conversation history, PRD Sec.8.1)
into chat messages, call OpenAI Chat Completions for whichever model
``variant.model_routing`` selects (falling back to the original span's model
when the variant doesn't touch this decision), and build a
``ReplayedDecision`` from the response.

GATED HARD. ``__init__`` raises unless BOTH:

  * ``TURNSTILE_ALLOW_PAID=1`` is set in the environment, AND
  * ``OPENAI_API_KEY`` is set (non-empty)

regardless of whether a ``client`` is injected -- the gate is about
authorizing a real spend, not about being able to construct a client. No
test in this package, and no default code path in ``run_experiments.py``,
sets ``TURNSTILE_ALLOW_PAID=1`` -- this class is exercised in tests only via
an injected fake client, with both env vars set to inert test values, so
nothing in this package's test suite ever reaches the network.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

from openai import OpenAI

from turnstile_schema import VariantSpec
from turnstile_schema.enums import DecisionKind
from turnstile_schema.spans import LlmDecide
from turnstile_replay.backend import ReplayContext, ReplayedDecision
# Wave-2 Item 2: the decision parser is the SHARED single source in
# turnstile_replay.decisions (the gate and this backend must parse
# identically); experiments depends on replay, so this re-import preserves
# the dependency direction. Behavior unchanged -- this module's tests stay
# green against the relocated parser.
from turnstile_replay.decisions import parse_decision_chosen

# A single stalled Chat Completions call must never hang the whole matrix
# (observed on the first n=30 smoke: no timeout -> the run blocked ~38min on
# one call). The OpenAI SDK applies BOTH a per-call ``timeout`` and bounded,
# backed-off ``max_retries`` (429 / >=500 / connection / timeout) when they are
# set on the client -- so we set them there rather than hand-rolling a retry
# loop that would double up with the SDK's own.
DEFAULT_REQUEST_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_PROGRESS_EVERY = 25

# M-3: a generous completion cap. The corpus's real output p95 is < 200
# tokens, so 256 never clips a normal reply while bounding a runaway
# generation (latency + cost lever). A reply that reaches the cap is logged
# as a suspected truncation.
DEFAULT_MAX_COMPLETION_TOKENS = 256

# The gpt-5 family are REASONING models: they spend completion-token budget on
# internal reasoning BEFORE any visible content. Smoke #3 measured every
# gpt-5-nano call consuming the whole 256-token cap on reasoning and returning
# EMPTY content (finish_reason="length") -> 100% false divergence. A routing/
# slot decision needs no deep reasoning, so we run the replayed model at
# minimal reasoning effort: verified non-empty content, ~125 completion tokens,
# and ~2s latency (vs ~9s) on the same prompt. Applied uniformly across the
# experiment, so it is a stated, consistent modeling choice, not per-trace
# tuning.
DEFAULT_REASONING_EFFORT = "minimal"


# Wave-2 Item 1b: kinds whose bounded label vocabulary is elicited verbatim
# in the replay prompt (the span's own decision_candidates supply the labels).
# slot_fill is deliberately absent (single-label, verdict-content-sensitive).
ELICITED_KINDS = frozenset({
    DecisionKind.route, DecisionKind.compose,
    DecisionKind.tool_select, DecisionKind.escalate_check,
})


def _render_messages(context: ReplayContext, original_span: LlmDecide) -> list[dict[str, str]]:
    """Pinned history (``ReplayContext.turns_before``) plus the CURRENT turn's
    caller-side ASR (``ReplayContext.current_turn_asr``, CR-A) rendered as a
    chat message list. Caller turns contribute their ASR transcript as a user
    message; agent turns contribute their own prior ``LlmDecide.output_text``
    as an assistant message -- the pinned conversation ``turnstile_replay``
    keeps fixed for every replayed trial (PRD Sec.8.1). The current turn's
    ASR transcript(s) come LAST as the final user message(s): that is the
    utterance the decision being replayed responds to (PRD Sec.8.1 pins the
    caller side of every turn, so deciding given it is faithful, not
    leakage)."""
    system = (
        f"You are the voice agent for scenario '{context.scenario_id}'. "
        f"Make the '{original_span.decision_kind.value}' decision for this turn."
    )
    # Wave-2 Item 1b elicitation contract: bounded multi-label kinds ask for
    # the verbatim label inside a natural reply (parseable, verdict content
    # reads intact). slot_fill is EXCLUDED -- single-label ["request_slot"]
    # plus verdict-content sensitivity: eliciting it would fake the verdict
    # signal, so it keeps the bare prompt until Item 2 treats it at value
    # level or excludes it explicitly.
    if (
        original_span.decision_kind in ELICITED_KINDS
        and original_span.decision_candidates
    ):
        labels = ", ".join(original_span.decision_candidates)
        system += (
            " Reply naturally, but include exactly one of these decision "
            f"labels verbatim in your reply: {labels}."
        )
    messages: list[dict[str, str]] = [{
        "role": "system",
        "content": system,
    }]
    for turn in context.turns_before:
        for asr in turn.asr:
            messages.append({"role": "user", "content": asr.transcript})
        for llm_span in turn.llm:
            messages.append({"role": "assistant", "content": llm_span.output_text})
    for asr in context.current_turn_asr:
        messages.append({"role": "user", "content": asr.transcript})
    return messages


def _cap_model(model: str, cap: str | None) -> str:
    """Substitute ``cap`` for any larger-bucket model when the cap is set; a
    model already in the small bucket (id ends ``-mini``/``-nano``) is left
    untouched. Lets a paid run stay inside OpenAI's shared-traffic small-model
    daily allowance (2.5M/day, tiers 1-2) instead of the 250k/day larger one.
    Quota-only: never applied on the deterministic mock path."""
    if not cap or model.endswith("-mini") or model.endswith("-nano"):
        return model
    return cap


class OpenAIBackend:
    def __init__(
        self,
        client: Any | None = None,
        *,
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        progress_every: int = DEFAULT_PROGRESS_EVERY,
        max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        model_cap: str | None = None,
    ) -> None:
        if os.environ.get("TURNSTILE_ALLOW_PAID") != "1":
            raise RuntimeError(
                "OpenAIBackend refuses to run: set TURNSTILE_ALLOW_PAID=1 to "
                "explicitly authorize real (paid) OpenAI API calls."
            )
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OpenAIBackend refuses to run: OPENAI_API_KEY is not set."
            )
        self._request_timeout_s = request_timeout_s
        self._progress_every = progress_every
        self._max_completion_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort
        # Free-tier quota lever: cap larger-bucket models (gpt-5) to a smaller-
        # bucket one on the PAID path, so a run draws from OpenAI's shared-traffic
        # small-model daily allowance (2.5M/day at tiers 1-2) instead of the
        # 250k/day larger bucket. Cost/quota-only -- the deterministic mock path
        # never constructs this backend, so headlines are untouched.
        self._model_cap = model_cap if model_cap is not None else (
            os.environ.get("TURNSTILE_PAID_MODEL_CAP") or None)
        if self._model_cap:
            print(
                f"[OpenAIBackend] model cap active: larger-bucket models sent as "
                f"'{self._model_cap}' (TURNSTILE_PAID_MODEL_CAP) to stay in the "
                f"small-model free daily allowance.",
                file=sys.stderr, flush=True,
            )
        # Change B (audit 06 Sec.6.2): the shared client runs across worker
        # threads; the progress counter is the only cross-call state and must
        # not lose increments or interleave its prints.
        self._calls_lock = threading.Lock()
        self._calls = 0
        self._client = client if client is not None else OpenAI(
            api_key=api_key, timeout=request_timeout_s, max_retries=max_retries
        )

    def __call__(
        self, context: ReplayContext, original_span: LlmDecide, variant: VariantSpec
    ) -> ReplayedDecision:
        model = original_span.gen_ai_request_model
        if variant.model_routing:
            model = variant.model_routing.get(original_span.decision_kind.value, model)
        model = _cap_model(model, self._model_cap)

        messages = _render_messages(context, original_span)
        start = time.monotonic()
        response = self._client.chat.completions.create(
            model=model, messages=messages,
            # M-3: bound runaway generations. The gpt-5 family (reasoning
            # models) rejects the legacy `max_tokens` with a 400 and requires
            # `max_completion_tokens` -- the fake-client tests can't see that,
            # so it only surfaced against the real API (smoke #3).
            max_completion_tokens=self._max_completion_tokens,
            reasoning_effort=self._reasoning_effort,  # keep reasoning from eating the whole cap
            timeout=self._request_timeout_s,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        with self._calls_lock:
            self._calls += 1
            announce = self._progress_every and self._calls % self._progress_every == 0
            calls = self._calls
        if announce:
            print(
                f"[OpenAIBackend] {calls} calls (last model={model}, "
                f"{latency_ms}ms)",
                file=sys.stderr,
                flush=True,
            )

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        # Truncation audit: on reasoning models completion_tokens INCLUDES
        # reasoning, so split it and report finish_reason -- otherwise the
        # next paid stderr can't tell "reasoning ate the cap" (harmless, raise
        # the cap or budget reasoning separately) from "content was clipped"
        # (a forced divergent trial that must be flagged, never silently
        # scored). Defensive getattr: test fakes carry no details block.
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
        finish_reason = getattr(choice, "finish_reason", None)
        if usage.completion_tokens >= self._max_completion_tokens:
            # M-3: a reply this long likely hit the cap and was truncated --
            # log it so the trial can be audited rather than silently biased.
            # Under the lock (same one guarding the progress counter): concurrent
            # worker threads sharing one stderr handle garbled these lines on the
            # n=250 paid re-run (reasoning/content tail lost in transport), and
            # the conversation id makes a truncated trial traceable.
            warning = (
                f"[OpenAIBackend] WARNING: completion reached max_tokens "
                f"cap ({usage.completion_tokens} >= {self._max_completion_tokens}); "
                f"model={model} conv={context.conversation_id} "
                f"finish_reason={finish_reason} "
                f"reasoning_tokens={reasoning_tokens} content_chars={len(text)} "
                f"-- possible truncation"
            )
            with self._calls_lock:
                print(warning, file=sys.stderr, flush=True)

        # M-2 / Section B4: `decision_chosen` is parsed per decision_kind
        # (escalate_check -> escalate/continue containment; tool_select -> the
        # candidate tool name contained in the utterance; every other kind ->
        # documented passthrough). The RAW completion utterance stays in
        # `output_text` verbatim. See parse_decision_chosen.
        # Wave-2 exp-hardening Item 1: the API's finish_reason rides on the
        # decision (Mock leaves None) so divergent/truncated trials can
        # self-document -- the replay layer persists it, never the schema.
        return ReplayedDecision(
            model=model,
            output_text=text,
            decision_chosen=parse_decision_chosen(
                original_span.decision_kind, text, original_span.decision_candidates
            ),
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
