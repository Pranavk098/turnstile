"""Waste-detection entry point -- packages/detectors (PRD §5).

Single entry point ``detect(trace, verdict, baselines) -> list[Finding]``. Runs
every registered detector and returns the union of their Findings. This wave
implements the five deterministic classes {2, 6, 7, 8, 10}; classes
{1, 3, 4, 5, 9} are judgment classes left for a later batch (see each
class's own module for its rule/waste derivation).
"""
from __future__ import annotations

from turnstile_schema import Baselines, Finding, PricedTrace, Verdict

from turnstile_detectors.d02_context_bloat import detect_context_bloat
from turnstile_detectors.d06_dead_tokens import detect_dead_tokens
from turnstile_detectors.d07_barge_in import detect_barge_in_waste
from turnstile_detectors.d08_silence_tax import detect_silence_tax
from turnstile_detectors.d10_tool_thrash import detect_tool_thrash

_REGISTRY = (
    detect_context_bloat,
    detect_dead_tokens,
    detect_barge_in_waste,
    detect_silence_tax,
    detect_tool_thrash,
)


def detect(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    findings: list[Finding] = []
    for detector in _REGISTRY:
        findings.extend(detector(trace, verdict, baselines))
    return findings
