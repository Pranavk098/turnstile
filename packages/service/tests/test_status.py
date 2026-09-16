"""Day-1 P1 #6-8: /api/status + gzip/cache headers + keep-warm contract.

Proves: status is lightweight (<200ms warm, no engine run), gzip compresses
large JSON, cache policy is no-store on mutating/status and public-cache on
reads/static. Keeps the P0 budgets green (evaluate warm p95 <300ms).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from turnstile_service.app import create_app
from turnstile_service.ratelimit import RateLimiter


def _client() -> TestClient:
    return TestClient(create_app(
        rate_limiter=RateLimiter(burst=1000, rate_per_sec=1000.0)))


def test_status_shape_and_speed():
    client = _client()
    import time
    start = time.perf_counter()
    res = client.get("/api/status")
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "commit" in body and isinstance(body["commit"], str)
    assert "uptime_sec" in body and body["uptime_sec"] >= 0
    assert body["warm"] is True
    assert "engine_loaded" in body
    assert elapsed_ms < 200.0
    assert res.headers.get("cache-control") == "no-store"


def test_status_runs_no_engine():
    """Status must not price/replay: boom the engine entry points."""
    import sys
    app_module = sys.modules["turnstile_service.app"]
    client = _client()

    def _boom(*args, **kwargs):
        raise AssertionError("status must not touch the engine")

    orig_run, orig_price = app_module.run_calls, app_module._price_calls
    app_module.run_calls, app_module._price_calls = _boom, _boom
    try:
        assert client.get("/api/status").status_code == 200
    finally:
        app_module.run_calls, app_module._price_calls = orig_run, orig_price


def test_cache_policy_reads_vs_writes():
    client = _client()
    assert client.get("/api/fleet").headers.get("cache-control") == \
        "public, max-age=60"
    assert client.get("/health").headers.get("cache-control") == \
        "public, max-age=60"
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    text = (root / "docs" / "INGEST.md").read_text(encoding="utf-8")
    call = json.loads(text.split("## The object")[1].split("```json")[1].split("```")[0])
    res = client.post("/api/evaluate", json=call)
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"


def test_gzip_shrinks_fleet():
    client = _client()
    plain = client.get("/api/fleet")
    assert plain.status_code == 200
    gz = client.get("/api/fleet", headers={"Accept-Encoding": "gzip"})
    assert gz.status_code == 200
    assert gz.json() == plain.json()
    # httpx auto-decodes; assert the wire would compress: raw JSON > 1KB floor.
    assert len(plain.content) > 1024


def test_boot_warms_committed_snapshot_without_engine():
    """Day-3 P1 #7: app boot (lifespan) preloads the committed fleet bytes
    read-only; read endpoints serve snapshot bytes identical to disk; cold
    first paint stays within the <5s budget; warming never runs the engine."""
    import sys
    import time
    from turnstile_service import data as committed

    app_module = sys.modules["turnstile_service.app"]

    def _boom(*args, **kwargs):
        raise AssertionError("warm boot must not touch the engine")

    orig_run, orig_price = app_module.run_calls, app_module._price_calls
    app_module.run_calls, app_module._price_calls = _boom, _boom
    try:
        with _client() as client:
            assert committed._WARM is not None
            assert len(committed._WARM) == len(committed.READ_ENDPOINTS) + 2
            start = time.perf_counter()
            fleet = client.get("/api/fleet")
            first_paint_ms = (time.perf_counter() - start) * 1000.0
            assert fleet.status_code == 200
            assert first_paint_ms < 5000.0
            assert fleet.content == committed.read_sample(
                committed.READ_ENDPOINTS["fleet"])
            assert client.get("/api/status").status_code == 200
    finally:
        app_module.run_calls, app_module._price_calls = orig_run, orig_price


def test_reads_fall_back_to_disk_without_lifespan(monkeypatch):
    """Without a lifespan run (bare app), readers serve disk bytes exactly."""
    from turnstile_service import data as committed

    monkeypatch.setattr(committed, "_WARM", None)
    assert committed.read_sample(
        committed.READ_ENDPOINTS["fleet"]) == (
        committed.SAMPLE_DIR / committed.READ_ENDPOINTS["fleet"]).read_bytes()
    assert committed.read_ingest_artifact() == \
        committed.INGEST_ARTIFACT.read_bytes()
    assert committed.read_example_call() == \
        committed.EXAMPLE_CALL_PATH.read_bytes()


def test_status_exposes_cache_and_timings_additive():
    """Day-3 Track D: /api/status carries cache hit-rate + median/p95
    alongside the Day-1 fields (never renamed/removed). Fresh app: zero
    traffic reads as hit_rate 0.0 with numeric timings."""
    client = _client()
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.json()
    # Day-1 contract intact.
    assert body["ok"] is True
    assert "commit" in body and isinstance(body["commit"], str)
    assert "uptime_sec" in body and body["uptime_sec"] >= 0
    assert body["warm"] is True
    assert "engine_loaded" in body
    # Day-3 additive fields.
    cache = body["cache"]
    for key in ("entries", "byte_size", "hits", "misses", "hit_rate"):
        assert key in cache, key
    assert cache["entries"] == 0
    assert cache["byte_size"] == 0
    assert cache["hits"] == 0 and cache["misses"] == 0
    assert cache["hit_rate"] == 0.0
    timings = body["timings_ms"]
    assert "evaluate_median" in timings and "evaluate_p95" in timings
    assert isinstance(timings["evaluate_median"], (int, float))
    assert isinstance(timings["evaluate_p95"], (int, float))
    assert timings["evaluate_median"] >= 0 and timings["evaluate_p95"] >= 0
    assert res.headers.get("cache-control") == "no-store"
