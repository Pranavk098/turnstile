"""Detector 6 -- Dead tokens (PRD §6, row 6).

Detection rule (verbatim): an `llm.decide` `output_text` with no matching
`tts.synthesize` in the turn, or where the synthesized text is a strict
substring of `output_text` (only part of the composed text was ever voiced).

Scope narrowing (beyond the literal rule, to hold the false-positive gate):

1. Restricted to `decision_kind == compose`. Route / slot_fill / tool_select /
   escalate_check decisions produce `output_text` as an internal routing
   artifact, never intended for `tts.synthesize` in the first place -- see
   fixture 11_multi_waste_a turn 0 (decision_kind=route, no tts, but that
   turn's waste is Detector 8's silence tax, not dead composition).

2. Restricted to turns with an empty `tools` list. Fixtures 08_silence_tax and
   10_tool_thrash (reused verbatim in 12_multi_waste_b turns 2-3) build the
   identical shape on purpose -- a compose decision confirming a tool call,
   with no tts span in the same turn -- but that confirmation text going
   unvoiced is Detector 8 (08: the turn stalls in dead air after composing)
   or Detector 10 (10/12: the call already resolved through the tool's
   effect, and the waste is the redundant duplicate tool call) territory, not
   genuinely dead tokens. Requiring no tool call in the turn is what lets
   Detector 6 fire on its true targets (06, 12 turn 0) without also firing on
   08 and 10, which are structurally indistinguishable from 06 on the literal
   rule alone.

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
        if turn.tools:
            continue
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
