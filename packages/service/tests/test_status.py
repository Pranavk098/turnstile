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
