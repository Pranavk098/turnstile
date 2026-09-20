"""Clean-venv smoke for turnstile-quality (Day-5 Part A).

Cheapest real entry point: summarize_quality (pure formatting,
no priced trace needed). No files, no network.
Prints ``ok quality <version>``, exits 0.
"""
from __future__ import annotations

from importlib.metadata import version


def main() -> None:
    from turnstile_quality.dimensions import summarize_quality

    line = summarize_quality("good", "measured", 0.05)
    assert line.startswith("quality:")
    print(f"ok quality {version('turnstile-quality')}")
