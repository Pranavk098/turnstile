"""Waste-detection entry point -- packages/detectors (PRD §5).

Single entry point ``detect(trace, verdict, baselines) -> list[Finding]``. Runs
every registered detector and returns the union of their Findings. All ten
classes are implemented: the deterministic classes {2, 6, 7, 8, 10} (batch A)
plus the judgment classes {1, 3, 4, 5, 9} (batch B, this wave -- see each
class's own module for its rule/waste derivation).
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, Verdict

from turnstile_detectors.d01_over_model import detect_over_model
from turnstile_detectors.d02_context_bloat import detect_context_bloat
from turnstile_detectors.d03_redundant_retrieval import detect_redundant_retrieval
from turnstile_detectors.d04_turn_inflation import detect_turn_inflation
from turnstile_detectors.d05_reprompt_loop import detect_reprompt_loop
from turnstile_detectors.d06_dead_tokens import detect_dead_tokens
from turnstile_detectors.d07_barge_in import detect_barge_in_waste
from turnstile_detectors.d08_silence_tax import detect_silence_tax
from turnstile_detectors.d09_escalation_debt import detect_escalation_debt
from turnstile_detectors.d10_tool_thrash import detect_tool_thrash

_REGISTRY = (
    detect_over_model,
    detect_context_bloat,
    detect_redundant_retrieval,
    detect_turn_inflation,
    detect_reprompt_loop,
    detect_dead_tokens,
    detect_barge_in_waste,
    detect_silence_tax,
    detect_escalation_debt,
    detect_tool_thrash,
)


def detect(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    findings: list[Finding] = []
    for detector in _REGISTRY:
        findings.extend(detector(trace, verdict, baselines))
    return findings
