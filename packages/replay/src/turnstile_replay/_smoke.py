"""Clean-venv smoke for turnstile-replay (Day-5 Part A).

Cheapest real entry point: wilson_interval (pure stats, no engine run).
No files, no network. Prints ``ok replay <version>``, exits 0.
"""
from __future__ import annotations

from importlib.metadata import version


def main() -> None:
    from turnstile_replay.stats import wilson_interval

    lo, hi = wilson_interval(8, 10)
    assert 0.0 <= lo <= hi <= 1.0
    print(f"ok replay {version('turnstile-replay')}")
