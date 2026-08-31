"""Detector 6 -- Dead tokens (PRD §6, row 6).

Detection rule (verbatim): an `llm.decide` `output_text` with no matching
`tts.synthesize` in the turn, or where the synthesized text is a strict
substring of `output_text` (only part of the composed text was ever voiced).

Scope narrowing (beyond the literal rule, to hold the false-positive gate):
restricted to `decision_kind == compose`. Route / slot_fill / tool_select /
escalate_check decisions produce `output_text` as an internal routing
artifact, never intended for `tts.synthesize` in the first place -- see
fixture 11_multi_waste_a turn 0 (decision_kind=route, no tts, but that turn's
waste is Detector 8's silence tax, not dead composition).

No `tools`-emptiness guard: an earlier revision restricted this detector to
turns with no `tool.call` spans, because 08_silence_tax and 10_tool_thrash
(reused in 12_multi_waste_b turns 2-3) build a compose-confirming-a-tool-call
shape that, with no tts span, was literally indistinguishable from 06's
genuine dead tokens. Ruling R13 (controller-directed, 2026-08-30): that was
the wrong fix -- those are real caller-facing compose turns (the agent
confirms "Checking now." / "Updating your address." to the caller), so
letting them go unvoiced was an unrealistic fixture, not a detector-scope
question. Fixed by voicing them in the fixtures instead (see
fixtures/golden/_author_rest.py's `# R13:` comments on 08/10/12); this
detector now implements the literal PRD rule with no tool-call exception.

Waste calculation (verbatim): unmatched `output_tokens x rate_out`. When a
tts span's text is a strict prefix of `output_text` (partial voicing), the
waste is the proportional share of output_tokens the un-voiced remainder
represents, estimated by character-length ratio (spans carry no per-word/
per-token text alignment, so tokens are assumed to spread evenly across the
composed text by character count).
"""
from __future__ import annotations

import re

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.enums import DecisionKind

from turnstile_detectors._rates import get_rates, llm_key

DEAD_TOKENS_CONFIDENCE = 0.95  # exact structural match, not statistical

# Fixture-authoring convention (see fixtures/golden/12_multi_waste_b turn 1's
# llm.output_text "...that continues well past where the caller interrupts."
# style shorthand): a trailing "..." on output_text marks an abbreviated
# compose whose full spoken form is the (longer) tts.text. Stripped before
# prefix-matching so that case is correctly treated as fully voiced.
_TRAILING_ELLIPSIS_RE = re.compile(r"\s*\.\.\.\s*$")


def _voiced_fraction(output_text: str, tts_texts: list[str]) -> float:
    """Fraction of output_text considered voiced by some tts span in the turn.
    1.0 = fully matched (no dead tokens); 0.0 = no matching tts span at all."""
    if not tts_texts:
        return 0.0
    key = _TRAILING_ELLIPSIS_RE.sub("", output_text)
    for text in tts_texts:
        if text == output_text or (key and text.startswith(key)):
            return 1.0
        if text and output_text.startswith(text):
            return len(text) / len(output_text)  # tts is a strict prefix -- partial voicing
    return 0.0


def detect_dead_tokens(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    rates = get_rates()
    findings: list[Finding] = []
    for turn in trace.trace.turns:
        tts_texts = [s.text for s in turn.tts]
        for span in turn.llm:
            if span.decision_kind != DecisionKind.compose:
                continue
            voiced = _voiced_fraction(span.output_text, tts_texts)
            if voiced >= 1.0:
                continue
            unmatched_tokens = span.output_tokens * (1.0 - voiced)
            rate = rates.llm[llm_key(span)]
            waste = unmatched_tokens / 1e6 * rate.output
            if waste <= 0:
                continue
            findings.append(
                Finding(
                    class_id=6,
                    turn_index=turn.turn_index,
                    span_id=span.span_id,
                    waste_usd=waste,
                    confidence=DEAD_TOKENS_CONFIDENCE,
                    proposed_variant=VariantSpec(tts_chunking="sentence"),
                    evidence={
                        "output_text": span.output_text,
                        "tts_texts": tts_texts,
                        "voiced_fraction": voiced,
                        "unmatched_output_tokens": unmatched_tokens,
                    },
                )
            )
    return findings
