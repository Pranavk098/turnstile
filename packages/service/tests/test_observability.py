"""Day-3 Track D: cache hit-rate + timing observability (EARS proofs).

- Timed double-POST to /api/evaluate (INGEST.md doc example): second is
  byte-identical and <50ms (cache-hit gate, charter §2).
- GET /api/status after a mixed load (5 cold + 5 hits) shows hit_rate in
  (0, 1) plus numeric median/p95 timings.
- Job poll result carries timings {queue_ms, run_ms} + worker count.
- EvalCache.stats() unit gate: counters, hit_rate, bounded median/p95.
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from turnstile_service.app import create_app
from turnstile_service.cache import EvalCache
from turnstile_service.ratelimit import RateLimiter

ROOT = Path(__file__).resolve().parents[3]


def _client() -> TestClient:
    return TestClient(create_app(
        rate_limiter=RateLimiter(burst=1000, rate_per_sec=1000.0)))


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    return json.loads(fence)


def test_double_post_byte_identical_and_fast():
    """WHEN the same call is evaluated twice, the second SHALL return
    byte-identical bytes from cache in <50ms."""
    client = _client()
    call = _doc_example()
    call["id"] = f"call-obs-{uuid.uuid4().hex[:8]}"  # cold key on a fresh cache
    first = client.post("/api/evaluate", json=call)
    assert first.status_code == 200
    t0 = time.perf_counter()
    second = client.post("/api/evaluate", json=call)
    hit_ms = (time.perf_counter() - t0) * 1000.0
    assert second.status_code == 200
    assert second.content == first.content
    assert hit_ms < 50.0, f"cache hit took {hit_ms:.1f}ms (>= 50ms budget)"


def test_status_hit_rate_and_timings_after_mixed_load():
    """WHILE observability is on, the service SHALL expose cache hit-rate +
    median/p95 timings after a mixed load."""
    client = _client()
    base = _doc_example()
    calls = []
    for i in range(5):
        dup = copy.deepcopy(base)
        dup["id"] = f"call-mix-{uuid.uuid4().hex[:8]}-{i}"
        calls.append(dup)
    for call in calls:  # 5 cold misses
        res = client.post("/api/evaluate", json=call)
        assert res.status_code == 200
    for call in calls:  # 5 cache hits
        res = client.post("/api/evaluate", json=call)
        assert res.status_code == 200
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.json()
    cache = body["cache"]
    assert cache["misses"] >= 5
    assert cache["hits"] >= 5
    assert 0.0 < cache["hit_rate"] < 1.0
    assert cache["entries"] >= 5 and cache["byte_size"] > 0
    timings = body["timings_ms"]
    assert isinstance(timings["evaluate_median"], (int, float))
    assert isinstance(timings["evaluate_p95"], (int, float))
    assert timings["evaluate_median"] >= 0
    assert timings["evaluate_p95"] >= timings["evaluate_median"]
    # After evaluate traffic the timings describe the eval handler itself.
    assert timings["source"] == "eval"
    assert res.headers.get("cache-control") == "no-store"


def test_status_timings_source_falls_back_to_cache_lookup():
    """With no evaluate traffic yet, timings_ms SHALL be labeled as
    cache-lookup timings, not presented as eval-handler timings."""
    client = _client()
    res = client.get("/api/status")
    assert res.status_code == 200
    timings = res.json()["timings_ms"]
    assert timings["source"] == "cache_lookup"
    assert isinstance(timings["evaluate_median"], (int, float))
    assert isinstance(timings["evaluate_p95"], (int, float))


def _poll_to_done(client: TestClient, job_id: str, timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        res = client.get(f"/api/experiments/{job_id}")
        assert res.status_code == 200, res.text
        status = res.json()["status"]
        assert status in ("queued", "running", "done", "error"), status
        if status in ("done", "error"):
            return res.json()
        assert time.monotonic() < deadline, "job never finished"
        time.sleep(0.02)


def test_job_result_carries_timings_and_workers():
    """The experiment job poll body SHALL carry timings {queue_ms, run_ms}
    plus a worker count, additively (existing keys intact)."""
    with TestClient(create_app(
            rate_limiter=RateLimiter(burst=1000, rate_per_sec=1000.0))) as client:
        res = client.post("/api/experiments", json={
            "calls": [_doc_example()],
            "variant": {"model_routing": {"route": "gpt-5-nano"}},
        })
        assert res.status_code == 202
        final = _poll_to_done(client, res.json()["job_id"])
        assert final["status"] == "done"
        timings = final["timings"]
        assert set(timings) >= {"queue_ms", "run_ms"}
        assert isinstance(timings["queue_ms"], (int, float))
        assert isinstance(timings["run_ms"], (int, float))
        assert timings["queue_ms"] >= 0 and timings["run_ms"] >= 0
        assert isinstance(final["workers"], int) and final["workers"] >= 1
        # Result payload intact: engine outputs only (the parallel==serial
        # byte-identity gate owns this dict; observability lives at the
        # poll envelope asserted above, never inside here).
        assert final["result"]["n_calls"] == 1
        assert "experiment" in final["result"] and "passes_gate" in final["result"]


def test_cache_stats_counters_and_hit_rate():
    cache = EvalCache()
    assert cache.get("missing") is None  # 1 miss
    assert cache.put("a", b"12") is True
    assert cache.get("a") == b"12"  # 1 hit
    stats = cache.stats()
    assert stats["entries"] == 1 and stats["byte_size"] == 2
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["hit_rate"] == 0.5
    assert stats["puts"] == 1 and stats["evictions"] == 0
    assert isinstance(stats["median_ms"], float) and stats["median_ms"] >= 0
    assert isinstance(stats["p95_ms"], float)
    assert stats["p95_ms"] >= stats["median_ms"]
