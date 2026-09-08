"""Mock-tool unit tests: fixed registry, fixed latencies, no I/O."""
from __future__ import annotations

from turnstile_live.tools import KNOWN_TOOLS, run_tool


def test_lookup_tool_has_no_effect():
    result = run_tool("lookup_invoices", {"order_id": "ORD-4481"})
    assert result.kind == "lookup"
    assert result.effect == "none"
    assert result.args == {"order_id": "ORD-4481"}


def test_mutation_tool_commits():
    result = run_tool("process_refund", {"order_id": "ORD-1", "amount_usd": 10.0})
    assert result.kind == "mutation"
    assert result.effect == "committed"


def test_unknown_tool_is_a_safe_lookup():
    """Never fail the loop on an unknown name: run it as an inert lookup so
    the call still records honestly (documented fallback, not a fabrication --
    the name is preserved verbatim)."""
    result = run_tool("mystery_widget", {})
    assert result.name == "mystery_widget"
    assert (result.kind, result.effect) == ("lookup", "none")


def test_tool_latencies_are_fixed():
    assert run_tool("lookup_invoices", {}).latency_ms == run_tool("lookup_invoices", {}).latency_ms
    assert set(KNOWN_TOOLS) >= {"lookup_invoices", "process_refund", "transfer_to_agent"}
