"""Clean-venv smoke for turnstile-detectors (Day-5 Part A).

Cheapest real entry point: detect on a minimal priced trace
(empty spans/verdict evidence, empty baselines — no findings expected).
No network. Prints ``ok detectors <version>``, exits 0.

NOTE (packaging debt, worked around here — not fixed): detectors load
``pricing/rates.yaml`` relative to the process CWD (see
``turnstile_detectors._rates``), so outside a repo checkout the file is
absent. The shim stages an empty-but-valid table in a temp CWD purely to
satisfy that load on a span-free trace (no span ever looks a rate up).
The CWD-relative load itself is a follow-up for the owning session
(ship the table as package data / resolve via importlib.resources).
No existing src logic is touched.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    from turnstile_detectors import detect
    from turnstile_schema import Baselines, PricedTrace, Verdict
    from turnstile_schema.enums import VerdictLabel
    from turnstile_schema.trace import Conversation, Trace, Turn

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trace = Trace(
        conversation=Conversation(
            conversation_id="smoke",
            agent_version="smoke",
            scenario_id="order_status",
            started_at=t0,
            ended_at=t0,
            end_reason="caller_hangup",
        ),
        turns=[Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=100)],
    )
    priced = PricedTrace(
        trace=trace,
        span_costs={},
        turn_costs=[0.0],
        conv_cost=0.0,
        stage_costs={"asr": 0.0, "llm": 0.0, "tts": 0.0, "telephony": 0.0},
    )
    verdict = Verdict(label=VerdictLabel.RESOLVED, confidence=1.0, evidence=[], turn_of_no_return=None)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "pricing").mkdir()
        (Path(tmp) / "pricing" / "rates.yaml").write_text(
            "asr: {}\nllm: {}\ntts: {}\ntelephony: {}\n", encoding="utf-8"
        )
        prev = os.getcwd()
        os.chdir(tmp)
        try:
            findings = detect(priced, verdict, Baselines(per_intent={}))
        finally:
            os.chdir(prev)
    assert isinstance(findings, list)
    print(f"ok detectors {version('turnstile-detectors')}")
