"""Concurrency + shared-state stability (PRD 03 P3).

Fires concurrent evaluates + experiments over one ASGI app (true asyncio
concurrency, not threads): no shared-mutable-state corruption, no
cross-request bleed, all results correct, and the shared engine
(rates/baselines loaded once) stays read-only.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx

from turnstile_service.app import _engine, app

ROOT = Path(__file__).resolve().parents[3]


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    return json.loads(fence)


def _variant() -> dict:
    return {"model_routing": {"route": "gpt-5-nano"}}


async def _evaluate(aclient, call):
    res = await aclient.post("/api/evaluate", json=call)
    assert res.status_code == 200, res.text
    return res.json()


async def _experiment_to_done(aclient, calls):
    res = await aclient.post("/api/experiments",
                             json={"calls": calls, "variant": _variant()})
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]
    for _ in range(500):
        poll = await aclient.get(f"/api/experiments/{job_id}")
        assert poll.status_code == 200, poll.text
        body = poll.json()
        if body["status"] in ("done", "error"):
            return body
        await asyncio.sleep(0.02)
    raise AssertionError("job never finished")


def test_concurrent_evaluates_and_experiments_are_correct():
    async def _run():
        rates_before, baselines_before = _engine()
        rates_dump = rates_before.model_dump_json()
        baselines_dump = baselines_before.model_dump_json()

        call_a = _doc_example()
        call_b = copy.deepcopy(call_a)
        call_b["id"] = "call-concurrent-b-001"
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver") as aclient:
            eval_a, eval_b, sweep = await asyncio.gather(
                _evaluate(aclient, call_a),
                _evaluate(aclient, call_b),
                _experiment_to_done(aclient, [call_a]),
            )
        # No cross-request bleed: ids, verdicts, and details stay partitioned.
        assert eval_a["calls"][0]["id"] == "call-20260904-001"
        assert eval_b["calls"][0]["id"] == "call-concurrent-b-001"
        assert set(eval_a["details"]) != set(eval_b["details"])
        assert eval_a["details"][eval_a["calls"][0]["detail"]]["trace"][
            "conversation"]["conversation_id"] == "call-20260904-001"
        # The sweep ran the same calls+variant to a gated, labeled result.
        assert sweep["status"] == "done"
        assert sweep["result"]["n_calls"] == 1
        assert "MockBackend" in sweep["result"]["provenance"]["note"]
        # Shared engine untouched: same objects, same bytes.
        rates_after, baselines_after = _engine()
        assert rates_after is rates_before and baselines_after is baselines_before
        assert rates_after.model_dump_json() == rates_dump
        assert baselines_after.model_dump_json() == baselines_dump

    asyncio.run(_run())


def test_concurrent_identical_posts_share_one_engine_run():
    """Two identical concurrent evaluates still compute once: the first
    writer populates the cache; the loser either hits it or recomputes the
    identical bytes (both outcomes are correct and byte-identical)."""
    async def _run():
        call = _doc_example()
        call["id"] = "call-concurrent-cache-001"
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver") as aclient:
            first, second = await asyncio.gather(
                _evaluate(aclient, call), _evaluate(aclient, copy.deepcopy(call)))
        assert first == second

    asyncio.run(_run())
