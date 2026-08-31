"""Detector 1 -- Over-model (PRD §6, row 1).

Detection rule (verbatim): `decision_kind ∈ {route, slot_fill, escalate_check}`
AND `output_tokens < 32` AND model tier = frontier (`gen_ai.request.model ==
"gpt-5"`). These three decision kinds are short, closed-candidate-set
decisions (which intent, which slot, whether to escalate) -- exactly the shape
that does not need a frontier model's reasoning depth. `compose`/`tool_select`
are deliberately excluded by the PRD rule itself (a long-form reply or a
tool-selection step can legitimately need more capability); only a literal
gpt-5 span with a short output on one of the three closed-decision kinds
qualifies.

Waste calculation (verbatim): `cost_llm(this span) − cost_llm(cheapest tier
serving the decision)`. Per this wave's brief, "cheapest tier" is pinned to
`gpt-5-nano` (not re-derived per decision_kind) -- rates.yaml's cheapest LLM
tier and the one the PRD's own D1 discussion assumes. `cost_llm(this span)` is
read from `PricedTrace.span_costs` (the already-priced actual cost); the
counterfactual at gpt-5-nano is recomputed locally with the identical PRD §4.2
token formula (mirrored from packages/pricing, not imported, per that
package's private-helper boundary -- see `_rates.py`'s module docstring for
why detectors re-derive rather than import pricing's internals).
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.enums import DecisionKind
from turnstile_schema.spans import LlmDecide

from turnstile_detectors._rates import get_rates

# PRD §6 D1, verbatim thresholds.
OVER_MODEL_DECISION_KINDS = (DecisionKind.route, DecisionKind.slot_fill, DecisionKind.escalate_check)
OVER_MODEL_OUTPUT_TOKEN_THRESHOLD = 32
OVER_MODEL_FRONTIER_MODEL = "gpt-5"
OVER_MODEL_CHEAPEST_TIER_MODEL = "gpt-5-nano"  # this wave's brief: pinned, not re-derived per decision_kind.
OVER_MODEL_CONFIDENCE = 0.9  # exact structural match (decision_kind/model/token-count), tier choice is pinned not derived.


def _cost_llm_at_rate(span: LlmDecide, rate) -> float:
    """PRD §4.2 cost_llm formula, verbatim, evaluated against a counterfactual rate."""
    return (
        (span.input_tokens - span.cache_read_tokens) / 1e6 * rate.input
        + span.cache_read_tokens / 1e6 * rate.cache_read
        + span.cache_write_tokens / 1e6 * rate.cache_write
        + (span.output_tokens + span.reasoning_tokens) / 1e6 * rate.output
    )


def detect_over_model(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    rates = get_rates()
    findings: list[Finding] = []
    for turn in trace.trace.turns:
        for span in turn.llm:
            if span.decision_kind not in OVER_MODEL_DECISION_KINDS:
                continue
            if span.output_tokens >= OVER_MODEL_OUTPUT_TOKEN_THRESHOLD:
                continue
            if span.gen_ai_request_model != OVER_MODEL_FRONTIER_MODEL:
                continue

            actual_cost = trace.span_costs[span.span_id]
            nano_key = f"{span.gen_ai_system}/{OVER_MODEL_CHEAPEST_TIER_MODEL}"
            nano_cost = _cost_llm_at_rate(span, rates.llm[nano_key])
            waste = actual_cost - nano_cost
            if waste <= 0:
                continue

            findings.append(
                Finding(
                    class_id=1,
                    turn_index=turn.turn_index,
                    span_id=span.span_id,
                    waste_usd=waste,
                    confidence=OVER_MODEL_CONFIDENCE,
                    proposed_variant=VariantSpec(
                        model_routing={span.decision_kind.value: OVER_MODEL_CHEAPEST_TIER_MODEL}
                    ),
                    evidence={
                        "decision_kind": span.decision_kind.value,
                        "model": span.gen_ai_request_model,
                        "output_tokens": span.output_tokens,
                        "actual_cost_usd": actual_cost,
                        "cheapest_tier_cost_usd": nano_cost,
                        "cheapest_tier_model": OVER_MODEL_CHEAPEST_TIER_MODEL,
                    },
                )
            )
    return findings
