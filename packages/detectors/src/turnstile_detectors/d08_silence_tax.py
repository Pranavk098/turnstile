"""Detector 8 -- Silence tax (PRD §6, row 8; see also docs/GATES.md G1).

Detection rule (verbatim): `active_ms(turn) = |union of [start_offset_ms,
start_offset_ms+duration_ms) across asr, llm.decide, tool.call, tts,
audio.playback|`; `silence_ms = billed_wall_ms - active_ms`. UNION, not sum --
overlapping spans must count once; a sum-of-durations instead of a union is
the bug this detector must not have.

Threshold: PRD §6 does not pin an exact millisecond value. `SILENCE_GAP_
THRESHOLD_MS` uses the convention the golden fixtures were authored against
(fixtures/golden/_author_rest.py's 08_silence_tax comment: "5200ms of dead air
(>200ms) with the telephony meter still running") as the noise floor between
real dead air and ordinary span-to-span scheduling jitter.

Waste calculation (verbatim): `silence_ms/1000 x telephony_rate_per_second`,
attributed by the span that starts next: model | tool | asr_endpoint |
tts_ttfb. For a gap strictly between two active spans (or before the first
one), that is literally the PRD-label of the next span's raw type (asr ->
asr_endpoint, llm -> model, tool -> tool, tts/playback -> tts_ttfb). A
*trailing* gap -- the turn ends before another span starts -- has no next
span to name, so it is attributed via `_TRAILING_GAP_NEXT_LABEL`, keyed off
the raw type of the last active span before the gap (what would naturally
have come next); this fallback is recorded in each finding's evidence as
`"trailing_gap": true` so it is auditable, not silently asserted.

docs/GATES.md G1: the live recorder cannot yet emit overlapping spans, so on
real traffic union == sum and D8 will systematically over-report silence/waste
until the TraceRecorder concurrency redesign lands. This implementation is
correct against the union formula regardless of that; fixtures 08 and
11_multi_waste_a are the detector's logic demo, not yet a trustworthy live
measurement (see G1 and LIMITATIONS.md).
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.trace import Turn

from turnstile_detectors._rates import get_rates, telephony_key

# fixtures/golden/_author_rest.py 08_silence_tax comment: ">200ms gap" is the
# fixture-authoring convention for "real" dead air (PRD §6 gives the rule but
# not a specific ms threshold).
SILENCE_GAP_THRESHOLD_MS = 200
SILENCE_TAX_CONFIDENCE = 0.9  # union/threshold-based, not a bare structural match

# PRD §6 D8 attribution label for the span that starts next, by its raw type.
_NEXT_LABEL = {"asr": "asr_endpoint", "tool": "tool", "llm": "model", "tts": "tts_ttfb", "playback": "tts_ttfb"}

# Trailing-gap fallback: label of what would naturally have come next, keyed
# by the raw type of the last active span before the gap (see module docstring).
_TRAILING_GAP_NEXT_LABEL = {
    "asr": "model",         # after ASR finishes, next is normally the LLM decision
    "tool": "model",        # after a tool call, next is normally the LLM composing a reply
    "llm": "tts_ttfb",      # after the LLM decides, next is normally TTS starting to speak
    "tts": "asr_endpoint",  # after TTS, next is normally the caller speaking again
    "playback": "asr_endpoint",
}


def _spans_by_raw_category(turn: Turn):
    for raw_category, spans in (
        ("asr", turn.asr), ("tool", turn.tools), ("llm", turn.llm),
        ("tts", turn.tts), ("playback", turn.playback),
    ):
        for span in spans:
            yield raw_category, span


def _proposed_variant(attributed_to: str) -> VariantSpec:
    if attributed_to == "tool":
        return VariantSpec(tool_batching=True)
    # model / tts_ttfb / asr_endpoint: the fix is a faster-responding tier for
    # the decision that's making the caller wait (PRD §6 D8 variant guidance).
    return VariantSpec(model_routing={"compose": "gpt-5-nano"})


def _finding(turn: Turn, gap_start: int, gap_end: int, next_raw: str | None,
             prev_raw: str | None, prev_span, rate_per_second: float) -> Finding:
    gap_ms = gap_end - gap_start
    trailing = next_raw is None
    attributed_to = _NEXT_LABEL[next_raw] if next_raw else _TRAILING_GAP_NEXT_LABEL.get(prev_raw, "model")
    span_id = prev_span.span_id if prev_span is not None else f"turn{turn.turn_index}:silence"

    return Finding(
        class_id=8,
        turn_index=turn.turn_index,
        span_id=span_id,
        waste_usd=gap_ms / 1000.0 * rate_per_second,
        confidence=SILENCE_TAX_CONFIDENCE,
        proposed_variant=_proposed_variant(attributed_to),
        evidence={
            "gap_start_ms": gap_start,
            "gap_end_ms": gap_end,
            "silence_ms": gap_ms,
            "billed_wall_ms": turn.wall_end_ms - turn.wall_start_ms,
            "attributed_to": attributed_to,
            "trailing_gap": trailing,
        },
    )


def detect_silence_tax(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    if trace.trace.telephony is None:
        return []
    rates = get_rates()
    leg = trace.trace.telephony
    rate_per_second = rates.telephony[telephony_key(leg)].rate / 60.0

    findings: list[Finding] = []
    for turn in trace.trace.turns:
        intervals = sorted(
            ((span.start_offset_ms, span.start_offset_ms + span.duration_ms, raw, span)
             for raw, span in _spans_by_raw_category(turn)),
            key=lambda iv: iv[0],
        )

        cursor = turn.wall_start_ms
        last_raw: str | None = None
        last_span = None
        for start, end, raw, span in intervals:
            if start - cursor > SILENCE_GAP_THRESHOLD_MS:
                findings.append(_finding(turn, cursor, start, raw, last_raw, last_span, rate_per_second))
            if end > cursor:
                cursor = end
                last_raw, last_span = raw, span

        if turn.wall_end_ms - cursor > SILENCE_GAP_THRESHOLD_MS:
            findings.append(_finding(turn, cursor, turn.wall_end_ms, None, last_raw, last_span, rate_per_second))

    return findings
