"""Detector 3 -- Redundant retrieval (PRD §6, row 3).

Detection rule (verbatim): a `tool.call` with `tool_kind=retrieval` whose
retrieved doc id ALSO appears in an earlier turn's `context.assemble.
retrieved_doc_ids`, OR `cosine(chunk, context) > 0.85`.

Two halves, per the PRD's "or":

* Structural half -- the doc-id overlap above (exact match; implemented in
  the first wave). Confidence 0.90: an exact id match, not a judgment.
* Cosine half (GAP-10, this change) -- `cosine(chunk, context) > 0.85` with
  the threshold verbatim from the PRD. "chunk" is the retrieval call's
  `query` (args_json's documented `{"query": ..., "doc_id": ...}` authoring
  convention); "context" is the conversation text already assembled before
  the retrieval turn (prior caller ASR transcripts + agent replies). The
  embedding model is a small LOCAL sentence-transformers model
  (``EMBEDDING_MODEL_NAME``, optional `embed` dependency group --
  ``uv sync --group embed``); it runs offline and, when the extra is absent
  or the model is not in the local cache, the cosine half is INERT (returns
  no signal) and D3 runs on its structural half alone -- a documented
  degradation, not an error. Confidence 0.75: an embedding-model judgment,
  below the structural half's exact match.

A retrieval that matches BOTH halves fires once, on the structural half
(exact evidence beats a similarity judgment).

`ToolCall` carries no structured doc-id field (schema v1.1's `tool.call` only
has `args_json`/`args_hash`/`result_hash`), so the retrieved doc id is parsed
out of `args_json` -- the fixture-authoring convention (fixtures/golden's
`03_redundant_retrieval`/`13_multi_waste_c`) is a JSON object with a `doc_id`
string key; a `doc_ids` list key is also accepted for forward-compatibility
with a multi-doc retrieval call, though no golden fixture exercises it. A
`tool.call` whose `args_json` carries neither key (i.e. every non-retrieval or
genuinely-novel retrieval call) is simply not a candidate -- no doc ids to
intersect.

Waste calculation (verbatim): "tool cost + `retrieved_tokens × rate_in`".
`retrieved_tokens` is not a `ToolCall` field either -- for the structural
half it is read off the EARLIEST prior turn's `context.assemble` span that
first retrieved the overlapping doc id (the token cost that call is now
redundantly paying again); for the cosine half, off the retrieval call's OWN
turn's `context.assemble` (the tokens this redundant call is adding now).
`rate_in` uses the model of the `llm.decide` span in the SAME turn as the
redundant tool call (the compose/route step this retrieval is feeding) --
every golden fixture's retrieval turn carries exactly one such span.
"""
from __future__ import annotations

import json
from functools import lru_cache

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.enums import ToolKind
from turnstile_schema.trace import Turn

from turnstile_detectors._rates import get_rates, llm_key

REDUNDANT_RETRIEVAL_CONFIDENCE = 0.9  # exact doc-id structural match; the cosine-similarity half is unimplemented.

# PRD §6 row 3, verbatim threshold for the cosine half (GAP-10).
COSINE_REDUNDANCY_THRESHOLD = 0.85
# The cosine half is an embedding-model judgment, not an exact id match.
COSINE_HALF_CONFIDENCE = 0.75
# Small LOCAL sentence-transformers model for the cosine half (optional
# `embed` dependency group; runs offline once cached locally).
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def _doc_ids_from_args(args_json: str) -> set[str]:
    try:
        args = json.loads(args_json)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(args, dict):
        return set()
    ids: set[str] = set()
    doc_id = args.get("doc_id")
    if isinstance(doc_id, str):
        ids.add(doc_id)
    doc_ids = args.get("doc_ids")
    if isinstance(doc_ids, list):
        ids.update(d for d in doc_ids if isinstance(d, str))
    return ids


def _query_from_args(args_json: str) -> str:
    """The retrieval's query text (the cosine half's "chunk"), per the same
    args_json authoring convention as the doc ids. Empty when absent."""
    try:
        args = json.loads(args_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(args, dict) and isinstance(args.get("query"), str):
        return args["query"]
    return ""


@lru_cache(maxsize=1)
def _load_embedder():
    """Load the local embedding model ONCE (optional `embed` extra). Raises
    when sentence-transformers is absent or the model is not locally cached;
    callers treat any failure as 'cosine half inert'."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _embed_similarity(text_a: str, text_b: str) -> float | None:
    """Cosine similarity of the two texts under the local embedding model,
    or ``None`` when the cosine half is inert (extra absent / model not
    cached offline). Never raises, never touches the network here: the model
    load either succeeds locally or the half degrades off."""
    try:
        model = _load_embedder()
    except Exception:
        return None
    vecs = model.encode([text_a, text_b], normalize_embeddings=True)
    a, b = vecs[0], vecs[1]
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = sum(float(x) * float(x) for x in a) ** 0.5
    norm_b = sum(float(x) * float(x) for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return None
    return dot / (norm_a * norm_b)


def detect_redundant_retrieval(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    rates = get_rates()
    findings: list[Finding] = []

    # doc_id -> (turn_index, retrieved_tokens) of the EARLIEST context.assemble that
    # surfaced it, built up turn by turn so only PRIOR turns can be matched against.
    prior_doc_tokens: dict[str, tuple[int, int]] = {}
    # The conversation text assembled BEFORE the current turn (caller ASR +
    # agent replies) -- the cosine half's "context".
    prior_context_text: list[str] = []

    for turn in trace.trace.turns:
        prior_text = " ".join(prior_context_text)

        for tool in turn.tools:
            if tool.tool_kind != ToolKind.retrieval:
                continue
            call_doc_ids = _doc_ids_from_args(tool.args_json)
            overlap = call_doc_ids & prior_doc_tokens.keys()
            if overlap:
                # If more than one overlapping doc, attribute to the first-retrieved one.
                doc_id = sorted(overlap, key=lambda d: prior_doc_tokens[d][0])[0]
                _origin_turn, retrieved_tokens = prior_doc_tokens[doc_id]

                turn_llm = turn.llm[0] if turn.llm else None
                rate_in = rates.llm[llm_key(turn_llm)].input if turn_llm is not None else None
                if rate_in is None:
                    continue  # no llm.decide in this turn to price the redundant tokens against.

                waste = tool.cost_usd + retrieved_tokens / 1e6 * rate_in
                if waste <= 0:
                    continue

                findings.append(
                    Finding(
                        class_id=3,
                        turn_index=turn.turn_index,
                        span_id=tool.span_id,
                        waste_usd=waste,
                        confidence=REDUNDANT_RETRIEVAL_CONFIDENCE,
                        proposed_variant=VariantSpec(retrieval_policy="threshold:0.8"),
                        evidence={
                            "half": "doc_id",
                            "doc_id": doc_id,
                            "first_retrieved_turn": _origin_turn,
                            "retrieved_tokens": retrieved_tokens,
                            "tool_cost_usd": tool.cost_usd,
                            "rate_in": rate_in,
                        },
                    )
                )
                continue  # structural half fired; the cosine half adds nothing here

            # Cosine half (GAP-10): PRD's `cosine(chunk, context) > 0.85`
            # alternative, on the retrieval's query vs the already-assembled
            # conversation text. Inert (no signal) without the optional
            # local embedding model. The waste formula is D3's verbatim one,
            # with retrieved_tokens read off THIS turn's context.assemble
            # (the tokens this redundant call adds now).
            query = _query_from_args(tool.args_json)
            if not query or not prior_text:
                continue
            similarity = _embed_similarity(query, prior_text)
            if similarity is None or similarity <= COSINE_REDUNDANCY_THRESHOLD:
                continue
            turn_llm = turn.llm[0] if turn.llm else None
            rate_in = rates.llm[llm_key(turn_llm)].input if turn_llm is not None else None
            if rate_in is None:
                continue
            retrieved_tokens = turn.context.retrieved_tokens if turn.context is not None else 0
            waste = tool.cost_usd + retrieved_tokens / 1e6 * rate_in
            if waste <= 0:
                continue
            findings.append(
                Finding(
                    class_id=3,
                    turn_index=turn.turn_index,
                    span_id=tool.span_id,
                    waste_usd=waste,
                    confidence=COSINE_HALF_CONFIDENCE,
                    proposed_variant=VariantSpec(retrieval_policy="threshold:0.8"),
                    evidence={
                        "half": "cosine",
                        "similarity": similarity,
                        "threshold": COSINE_REDUNDANCY_THRESHOLD,
                        "embedding_model": EMBEDDING_MODEL_NAME,
                        "query": query,
                        "retrieved_tokens": retrieved_tokens,
                        "tool_cost_usd": tool.cost_usd,
                        "rate_in": rate_in,
                    },
                )
            )

        _record_context_doc_ids(turn, prior_doc_tokens)
        for asr in turn.asr:
            prior_context_text.append(asr.transcript)
        for llm_span in turn.llm:
            prior_context_text.append(llm_span.output_text)

    return findings


def _record_context_doc_ids(turn: Turn, prior_doc_tokens: dict[str, tuple[int, int]]) -> None:
    if turn.context is None:
        return
    for doc_id in turn.context.retrieved_doc_ids:
        if doc_id not in prior_doc_tokens:
            prior_doc_tokens[doc_id] = (turn.turn_index, turn.context.retrieved_tokens)
