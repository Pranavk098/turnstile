"""Mock tool layer: a fixed registry with fixed latencies, no I/O.

Every entry is honest mock telemetry (see turnstile_live.loop): the loop runs
these instead of real tools so Phase 1 stays free and deterministic. Unknown
names degrade to an inert lookup -- the name is preserved verbatim, so the
fallback is visible in the emitted call, never a fabrication.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# name -> (kind, effect, latency_ms). Kinds/effects are ingest-vocabulary
# strings (docs/INGEST.md); validated again at IngestCall construction.
KNOWN_TOOLS: dict[str, tuple[str, str, int]] = {
    "lookup_account": ("lookup", "none", 300),
    "lookup_invoices": ("lookup", "none", 300),
    "retrieve_kb_article": ("retrieval", "none", 400),
    "process_refund": ("mutation", "committed", 500),
    "adjust_billing": ("mutation", "committed", 500),
    "reschedule_appointment": ("mutation", "committed", 500),
    "cancel_subscription": ("mutation", "committed", 500),
    "transfer_to_agent": ("handoff", "committed", 200),
}

_FALLBACK: tuple[str, str, int] = ("lookup", "none", 300)


@dataclass(frozen=True)
class ToolResult:
    """What a mock tool run produced (feeds one ingest `tools[]` entry)."""

    name: str
    kind: str
    effect: str
    args: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 300


def run_tool(name: str, args: dict[str, Any] | None = None) -> ToolResult:
    """Run the named mock tool. Unknown names run as inert lookups."""
    kind, effect, latency_ms = KNOWN_TOOLS.get(name, _FALLBACK)
    return ToolResult(
        name=name, kind=kind, effect=effect,
        args=dict(args) if args else {}, latency_ms=latency_ms,
    )
