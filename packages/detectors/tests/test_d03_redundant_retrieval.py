"""Unit tests for Detector 3 -- redundant retrieval (PRD §6 row 3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from turnstile_schema import load_rates, load_trace
from turnstile_schema.enums import ToolKind
from turnstile_pricing import price_trace
from turnstile_detectors.d03_redundant_retrieval import detect_redundant_retrieval

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, context, llm, priced, tool, turn

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"


def test_fires_when_retrieval_doc_id_matches_earlier_context():
    pt = priced(
        turn(0, 0, 500, context_span=context("c0", start=0, retrieved_tokens=600,
                                              retrieved_doc_ids=["doc_7"]),
             llm_spans=[llm("l0", start=0, input_tokens=700, output_tokens=18)]),
        turn(1, 500, 900, tools=[
            tool("tool1", start=500, name="search_kb", kind=ToolKind.retrieval,
                 args_json='{"query": "refund policy", "doc_id": "doc_7"}')
        ], llm_spans=[llm("l1", start=800, input_tokens=800, output_tokens=25)]),
    )
    findings = detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 3
    assert f.turn_index == 1 and f.span_id == "tool1"
    assert f.proposed_variant.retrieval_policy == "threshold:0.8"
    # tool cost 0.0 + 600 retrieved_tokens x gpt-5-mini input rate 0.25
    assert f.waste_usd == pytest.approx(600 / 1e6 * 0.25)


def test_silent_when_doc_id_is_novel():
    pt = priced(
        turn(0, 0, 500, context_span=context("c0", start=0, retrieved_tokens=600,
                                              retrieved_doc_ids=["doc_7"]),
             llm_spans=[llm("l0", start=0, input_tokens=700, output_tokens=18)]),
        turn(1, 500, 900, tools=[
            tool("tool1", start=500, name="search_kb", kind=ToolKind.retrieval,
                 args_json='{"query": "billing", "doc_id": "doc_99"}')
        ], llm_spans=[llm("l1", start=800, input_tokens=800, output_tokens=25)]),
    )
    assert detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_doc_appears_only_in_the_same_turn():
    # A context.assemble and a retrieval tool.call sharing the doc id in the SAME
    # turn is not "an earlier turn" -- must not fire.
    pt = priced(
        turn(0, 0, 500,
             context_span=context("c0", start=0, retrieved_tokens=600, retrieved_doc_ids=["doc_7"]),
             tools=[tool("tool0", start=0, name="search_kb", kind=ToolKind.retrieval,
                          args_json='{"doc_id": "doc_7"}')],
             llm_spans=[llm("l0", start=0, input_tokens=700, output_tokens=18)]),
    )
    assert detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_silent_when_tool_kind_is_not_retrieval():
    pt = priced(
        turn(0, 0, 500, context_span=context("c0", start=0, retrieved_tokens=600,
                                              retrieved_doc_ids=["doc_7"]),
             llm_spans=[llm("l0", start=0, input_tokens=700, output_tokens=18)]),
        turn(1, 500, 900, tools=[
            tool("tool1", start=500, name="lookup_order", kind=ToolKind.lookup,
                 args_json='{"doc_id": "doc_7"}')
        ], llm_spans=[llm("l1", start=800, input_tokens=800, output_tokens=25)]),
    )
    assert detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_golden_fixture_03_fires_with_expected_waste():
    pt = price_trace(load_trace(GOLDEN / "03_redundant_retrieval.json"), load_rates(RATES))
    findings = detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.turn_index == 2 and f.span_id == "tool2"
    assert f.waste_usd == pytest.approx(600 / 1e6 * 0.25)
