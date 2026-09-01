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
import time
from typing import Any

from openai import OpenAI

from turnstile_schema import VariantSpec
from turnstile_schema.spans import LlmDecide
from turnstile_replay.backend import ReplayContext, ReplayedDecision

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
    messages: list[dict[str, str]] = [{
        "role": "system",
        "content": (
            f"You are the voice agent for scenario '{context.scenario_id}'. "
            f"Make the '{original_span.decision_kind.value}' decision for this turn."
        ),
    }]
    for turn in context.turns_before:
        for asr in turn.asr:
            messages.append({"role": "user", "content": asr.transcript})
        for llm_span in turn.llm:
            messages.append({"role": "assistant", "content": llm_span.output_text})
    for asr in context.current_turn_asr:
        messages.append({"role": "user", "content": asr.transcript})
    return messages


class OpenAIBackend:
    def __init__(
        self,
        client: Any | None = None,
        *,
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        progress_every: int = DEFAULT_PROGRESS_EVERY,
        max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
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

        messages = _render_messages(context, original_span)
        start = time.monotonic()
        response = self._client.chat.completions.create(
            model=model, messages=messages,
            max_tokens=self._max_completion_tokens,  # M-3: bound runaway generations
            timeout=self._request_timeout_s,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        self._calls += 1
        if self._progress_every and self._calls % self._progress_every == 0:
            print(
                f"[OpenAIBackend] {self._calls} calls (last model={model}, "
                f"{latency_ms}ms)",
                file=sys.stderr,
                flush=True,
            )

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        if usage.completion_tokens >= self._max_completion_tokens:
            # M-3: a reply this long likely hit the cap and was truncated --
            # log it so the trial can be audited rather than silently biased.
            print(
                f"[OpenAIBackend] WARNING: completion reached max_tokens "
                f"cap ({usage.completion_tokens} >= {self._max_completion_tokens}); "
                f"model={model} -- possible truncation",
                file=sys.stderr,
                flush=True,
            )

        # M-2 (documented at the ReplayedDecision boundary): `decision_chosen`
        # here is the RAW completion utterance, not a parsed decision value.
        # Wave-1 proxies it; per-decision_kind parsing (escalate_check ->
        # escalate/continue, tool_select -> tool name) is queued for Wave-2.
        return ReplayedDecision(
            model=model,
            output_text=text,
            decision_chosen=text,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
        )
