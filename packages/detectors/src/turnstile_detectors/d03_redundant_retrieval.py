"""Detector 3 -- Redundant retrieval (PRD §6, row 3).

Detection rule (verbatim, structural half only -- see scope note): a
`tool.call` with `tool_kind=retrieval` whose retrieved doc id ALSO appears in
an earlier turn's `context.assemble.retrieved_doc_ids`. (The PRD rule also
offers a `cosine(chunk, context) > 0.85` alternative; that requires an
embedding model this wave does not have and is out of scope -- only the
doc-id-overlap half is implemented, per this wave's brief.)

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
`retrieved_tokens` is not a `ToolCall` field either -- it is read off the
EARLIEST prior turn's `context.assemble` span that first retrieved the
overlapping doc id (the token cost that call is now redundantly paying again).
`rate_in` uses the model of the `llm.decide` span in the SAME turn as the
redundant tool call (the compose/route step this retrieval is feeding) --
every golden fixture's retrieval turn carries exactly one such span.
"""
from __future__ import annotations

import json

from turnstile_schema import Baselines, Finding, PricedTrace, VariantSpec, Verdict
from turnstile_schema.enums import ToolKind
from turnstile_schema.trace import Turn

from turnstile_detectors._rates import get_rates, llm_key

REDUNDANT_RETRIEVAL_CONFIDENCE = 0.9  # exact doc-id structural match; the cosine-similarity half is unimplemented.


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


def detect_redundant_retrieval(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]:
    rates = get_rates()
    findings: list[Finding] = []

    # doc_id -> (turn_index, retrieved_tokens) of the EARLIEST context.assemble that
    # surfaced it, built up turn by turn so only PRIOR turns can be matched against.
    prior_doc_tokens: dict[str, tuple[int, int]] = {}

    for turn in trace.trace.turns:
        for tool in turn.tools:
            if tool.tool_kind != ToolKind.retrieval:
                continue
            call_doc_ids = _doc_ids_from_args(tool.args_json)
            overlap = call_doc_ids & prior_doc_tokens.keys()
            if not overlap:
                continue

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
                        "doc_id": doc_id,
                        "first_retrieved_turn": _origin_turn,
                        "retrieved_tokens": retrieved_tokens,
                        "tool_cost_usd": tool.cost_usd,
                        "rate_in": rate_in,
                    },
                )
            )

        _record_context_doc_ids(turn, prior_doc_tokens)

    return findings


def _record_context_doc_ids(turn: Turn, prior_doc_tokens: dict[str, tuple[int, int]]) -> None:
    if turn.context is None:
        return
    for doc_id in turn.context.retrieved_doc_ids:
        if doc_id not in prior_doc_tokens:
            prior_doc_tokens[doc_id] = (turn.turn_index, turn.context.retrieved_tokens)
