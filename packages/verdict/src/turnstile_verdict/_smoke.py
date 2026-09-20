"""Clean-venv smoke for turnstile-verdict (Day-5 Part A).

Cheapest real entry point: registry lookup (no trace needed).
No files, no network. Prints ``ok verdict <version>``, exits 0.
"""
from __future__ import annotations

from importlib.metadata import version


def main() -> None:
    from turnstile_verdict import lookup

    spec = lookup("refund")
    assert spec is not None and spec.requires_mutation == "process_refund"
    assert lookup("no-such-scenario") is None
    print(f"ok verdict {version('turnstile-verdict')}")
