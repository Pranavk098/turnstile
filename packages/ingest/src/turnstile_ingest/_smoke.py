"""Clean-venv smoke for turnstile-ingest (Day-5 Part A).

Cheapest real entry point: validate a minimal one-turn IngestCall
in memory (no adapter run, no files). No network.
Prints ``ok ingest <version>``, exits 0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version


def main() -> None:
    from turnstile_ingest.model import IngestCall, IngestTurn

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    call = IngestCall(
        id="smoke",
        scenario="order_status",
        started=t0,
        ended=t0,
        end_reason="caller_hangup",
        turns=[IngestTurn(start_ms=0, end_ms=100)],
    )
    assert call.turns[0].end_ms == 100
    print(f"ok ingest {version('turnstile-ingest')}")
