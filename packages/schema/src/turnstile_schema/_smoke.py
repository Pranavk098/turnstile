"""Clean-venv smoke for turnstile-schema (Day-5 Part A).

Cheapest real entry point: validate a one-entry RateTable in memory.
No files, no network. Prints ``ok schema <version>``, exits 0.
"""
from __future__ import annotations

from importlib.metadata import version


def main() -> None:
    from turnstile_schema.rates import (
        AsrRate,
        LlmRate,
        RateTable,
        TelephonyRate,
        TtsRate,
    )

    table = RateTable(
        asr={"s": AsrRate(unit="audio_minute", rate=1.0)},
        llm={"m": LlmRate(unit="mtok", input=1.0, output=2.0)},
        tts={"t": TtsRate(unit="char_1k", rate=1.0)},
        telephony={"p": TelephonyRate(unit="minute", rate=1.0)},
    )
    assert table.llm["m"].output == 2.0
    print(f"ok schema {version('turnstile-schema')}")
