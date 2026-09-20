"""Clean-venv smoke for turnstile-pricing (Day-5 Part A).

Cheapest real entry point: price_trace on a one-turn, span-free trace
(zero cost expected). No files, no network.
Prints ``ok pricing <version>``, exits 0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version


def main() -> None:
    from turnstile_pricing import price_trace
    from turnstile_schema.rates import (
        AsrRate,
        LlmRate,
        RateTable,
        TelephonyRate,
        TtsRate,
    )
    from turnstile_schema.trace import Conversation, Trace, Turn

    rates = RateTable(
        asr={"s": AsrRate(unit="audio_minute", rate=1.0)},
        llm={"m": LlmRate(unit="mtok", input=1.0, output=2.0)},
        tts={"t": TtsRate(unit="char_1k", rate=1.0)},
        telephony={"p": TelephonyRate(unit="minute", rate=1.0)},
    )
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
    priced = price_trace(trace, rates)
    assert priced.conv_cost == 0.0
    print(f"ok pricing {version('turnstile-pricing')}")
