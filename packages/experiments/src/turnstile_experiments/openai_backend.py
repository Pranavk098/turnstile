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
import time
from typing import Any

from openai import OpenAI

from turnstile_schema import VariantSpec
from turnstile_schema.spans import LlmDecide
from turnstile_replay.backend import ReplayContext, ReplayedDecision


def _render_messages(context: ReplayContext, original_span: LlmDecide) -> list[dict[str, str]]:
    """Pinned history (``ReplayContext.turns_before``) rendered as a chat
    message list. Caller turns contribute their ASR transcript as a user
    message; agent turns contribute their own prior ``LlmDecide.output_text``
    as an assistant message -- the pinned conversation ``turnstile_replay``
    keeps fixed for every replayed trial (PRD Sec.8.1)."""
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
    return messages


class OpenAIBackend:
    def __init__(self, client: Any | None = None) -> None:
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
        self._client = client if client is not None else OpenAI(api_key=api_key)

    def __call__(
        self, context: ReplayContext, original_span: LlmDecide, variant: VariantSpec
    ) -> ReplayedDecision:
        model = original_span.gen_ai_request_model
        if variant.model_routing:
            model = variant.model_routing.get(original_span.decision_kind.value, model)

        messages = _render_messages(context, original_span)
        start = time.monotonic()
        response = self._client.chat.completions.create(model=model, messages=messages)
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage

        return ReplayedDecision(
            model=model,
            output_text=text,
            decision_chosen=text,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
        )
