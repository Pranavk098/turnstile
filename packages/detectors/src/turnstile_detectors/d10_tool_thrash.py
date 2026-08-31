"""Detector 10 -- Tool thrash (PRD §6, row 10).

Detection rule (verbatim): duplicate `args_hash` for the same `tool_name`
within a conversation. The first occurrence of a (tool_name, args_hash) pair
is the legitimate call; every later occurrence is a redundant repeat of work
already done (golden fixture 10's own builder comment: "both calls actually
succeeded (effect=committed) -- the waste is the redundant second call, not a
failed first one").

Waste calculation (verbatim): "cost of the duplicate calls + their turns".
`ToolCall.cost_usd` is the vendor-reported cost of the call itself; it is
deliberately excluded from `PricedTrace.span_costs`/`stage_costs` by
`packages/pricing` (it is metadata, not a rate-priced stage), so it is added
back in here directly. "Their turns" is each duplicate's `PricedTrace.
turn_costs` entry -- the whole turn (LLM confirmation, any TTS/telephony time
attributed to it) exists only because of the redundant call.
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict

TOOL_THRASH_CONFIDENCE = 0.95  # exact structural match, not statistical


def detect_tool_thrash(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    seen: set[tuple[str, str]] = set()
    findings: list[Finding] = []
    for i, turn in enumerate(trace.trace.turns):
        for tool in turn.tools:
            key = (tool.tool_name, tool.args_hash)
            if key in seen:
                turn_cost = trace.turn_costs[i]
                findings.append(
                    Finding(
                        class_id=10,
                        turn_index=turn.turn_index,
                        span_id=tool.span_id,
                        waste_usd=turn_cost + tool.cost_usd,
                        confidence=TOOL_THRASH_CONFIDENCE,
                        proposed_variant=VariantSpec(tool_batching=True),
                        evidence={
                            "tool_name": tool.tool_name,
                            "args_hash": tool.args_hash,
                            "turn_cost_usd": turn_cost,
                            "tool_cost_usd": tool.cost_usd,
                        },
                    )
                )
            else:
                seen.add(key)
    return findings
