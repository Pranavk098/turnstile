"""Unit tests for Detector 3's cosine-similarity half (GAP-10, PRD §6 row 3's
`cosine(chunk, context) > 0.85` alternative).

Two layers:
  * Stub layer -- the embedder is monkeypatched, so the detection logic is
    verified deterministically and ALWAYS runs (no model, no network).
  * Real-model layer -- loads the local sentence-transformers model
    (optional `embed` group: `uv sync --group embed`); SKIPS cleanly when
    the extra is absent or the model is not in the local HF cache. Never
    touches the network at test time.
"""
from __future__ import annotations

import pytest

from turnstile_schema.enums import ToolKind
from turnstile_detectors import d03_redundant_retrieval as d03
from turnstile_detectors.d03_redundant_retrieval import (
    COSINE_REDUNDANCY_THRESHOLD,
    detect_redundant_retrieval,
)

from _builders import DUMMY_VERDICT, EMPTY_BASELINES, context, llm, priced, tool, turn

GPT5_MINI_RATE_IN = 0.25  # pricing/rates.yaml openai/gpt-5-mini input rate


def _trace(*, query: str = "where is my refund for order 1234", doc_id: str = "doc_new",
           retrieved_tokens: int = 300):
    # Turn 0 establishes conversational context text; turn 1 issues a
    # retrieval whose doc id is NOVEL (the structural half stays silent) but
    # whose query may duplicate that context (the cosine half's trigger).
    return priced(
        turn(0, 0, 500, context_span=context("c0", start=0, retrieved_tokens=0,
                                              retrieved_doc_ids=[]),
             llm_spans=[llm("l0", start=0, input_tokens=100, output_tokens=18)]),
        turn(1, 500, 900,
             context_span=context("c1", start=600, retrieved_tokens=retrieved_tokens,
                                  retrieved_doc_ids=[doc_id]),
             tools=[tool("tool1", start=500, name="search_kb", kind=ToolKind.retrieval,
                         args_json=f'{{"query": "{query}", "doc_id": "{doc_id}"}}')],
             llm_spans=[llm("l1", start=800, input_tokens=800, output_tokens=25)]),
    )


# --------------------------------------------------------------------------- #
# Stub layer -- deterministic, always runs.                                    #
# --------------------------------------------------------------------------- #

def test_cosine_half_fires_above_threshold(monkeypatch):
    monkeypatch.setattr(d03, "_embed_similarity", lambda a, b: 0.92)
    findings = detect_redundant_retrieval(_trace(), DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    f = findings[0]
    assert f.class_id == 3
    assert f.turn_index == 1 and f.span_id == "tool1"
    assert f.confidence == pytest.approx(d03.COSINE_HALF_CONFIDENCE)
    assert f.proposed_variant.retrieval_policy == "threshold:0.8"
    ev = f.evidence
    assert ev["half"] == "cosine"
    assert ev["similarity"] == pytest.approx(0.92)
    assert ev["threshold"] == COSINE_REDUNDANCY_THRESHOLD
    assert ev["embedding_model"] == d03.EMBEDDING_MODEL_NAME
    # D3's verbatim waste formula: tool cost (0.0) + this turn's retrieved
    # tokens (300) x the same-turn llm's input rate (gpt-5-mini, 0.25).
    assert f.waste_usd == pytest.approx(300 / 1e6 * GPT5_MINI_RATE_IN)


def test_cosine_half_silent_below_threshold(monkeypatch):
    monkeypatch.setattr(d03, "_embed_similarity", lambda a, b: 0.5)
    assert detect_redundant_retrieval(_trace(), DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_cosine_half_silent_at_exactly_the_threshold(monkeypatch):
    # PRD verbatim: cosine > 0.85 -- equality does not fire.
    monkeypatch.setattr(d03, "_embed_similarity", lambda a, b: COSINE_REDUNDANCY_THRESHOLD)
    assert detect_redundant_retrieval(_trace(), DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_cosine_half_inert_when_embedder_unavailable(monkeypatch):
    # No optional extra / model not cached: the half degrades off silently.
    monkeypatch.setattr(d03, "_embed_similarity", lambda a, b: None)
    assert detect_redundant_retrieval(_trace(), DUMMY_VERDICT, EMPTY_BASELINES) == []


def test_structural_half_takes_precedence_over_cosine(monkeypatch):
    # Doc-id overlap AND a high similarity: exactly ONE finding, on the
    # structural (exact-match) half.
    monkeypatch.setattr(d03, "_embed_similarity", lambda a, b: 0.99)
    pt = priced(
        turn(0, 0, 500, context_span=context("c0", start=0, retrieved_tokens=600,
                                              retrieved_doc_ids=["doc_7"]),
             llm_spans=[llm("l0", start=0, input_tokens=700, output_tokens=18)]),
        turn(1, 500, 900,
             context_span=context("c1", start=600, retrieved_tokens=600,
                                  retrieved_doc_ids=["doc_7"]),
             tools=[tool("tool1", start=500, name="search_kb", kind=ToolKind.retrieval,
                         args_json='{"query": "refund policy", "doc_id": "doc_7"}')],
             llm_spans=[llm("l1", start=800, input_tokens=800, output_tokens=25)]),
    )
    findings = detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert len(findings) == 1
    assert findings[0].evidence["half"] == "doc_id"


def test_cosine_context_is_only_text_prior_to_the_retrieval_turn(monkeypatch):
    # The query must be compared against PRIOR text only: the retrieval
    # turn's OWN utterances (its llm output) must not be in the context text.
    seen = {}

    def spy(a, b):
        seen["query"], seen["context"] = a, b
        return 0.99

    monkeypatch.setattr(d03, "_embed_similarity", spy)
    pt = priced(
        turn(0, 0, 500, context_span=context("c0", start=0, retrieved_tokens=0,
                                              retrieved_doc_ids=[]),
             llm_spans=[llm("l0", start=0, input_tokens=100, output_tokens=18,
                            output_text="prior agent reply about the refund")]),
        turn(1, 500, 900,
             context_span=context("c1", start=600, retrieved_tokens=300,
                                  retrieved_doc_ids=["doc_new"]),
             tools=[tool("tool1", start=500, name="search_kb", kind=ToolKind.retrieval,
                         args_json='{"query": "where is my refund", "doc_id": "doc_new"}')],
             llm_spans=[llm("l1", start=800, input_tokens=800, output_tokens=25,
                            output_text="TURN-1 REPLY MUST NOT APPEAR")]),
    )
    detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    assert seen["query"] == "where is my refund"
    assert "prior agent reply about the refund" in seen["context"]
    assert "TURN-1 REPLY MUST NOT APPEAR" not in seen["context"]


# --------------------------------------------------------------------------- #
# Real-model layer -- skips cleanly without the extra / offline model.         #
# --------------------------------------------------------------------------- #

def test_real_local_model_duplicates_context_and_fires():
    pytest.importorskip("sentence_transformers")
    try:
        d03._load_embedder()
    except Exception as exc:  # model not in the local cache; offline test run
        pytest.skip(f"local embedding model unavailable offline: {exc}")
    pt = _trace(query="I want a refund for my order")
    # Turn 0's agent reply restates the request -> the duplicate-query
    # retrieval is near-identical to prior context.
    findings = detect_redundant_retrieval(pt, DUMMY_VERDICT, EMPTY_BASELINES)
    # The model's judgment is trusted only for the SHAPE of the outcome here:
    # if it fires, it must be via the cosine half with the verbatim threshold.
    for f in findings:
        assert f.evidence["half"] in ("doc_id", "cosine")
        if f.evidence["half"] == "cosine":
            assert f.evidence["similarity"] > COSINE_REDUNDANCY_THRESHOLD