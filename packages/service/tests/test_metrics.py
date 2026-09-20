"""Day-5 Part C: /metrics + structured logging + Sentry wiring.

- /metrics 200 with keys rendered from Day-3's existing counters; wall <50ms.
- /api/status shape frozen (additive-only: exact Day-3 key sets intact).
- Logging overhead: median(HTTP GET /metrics) minus median(direct
  in-process metrics_snapshot()) < 5ms (method: the direct call bypasses the
  HTTP middleware, so the delta is the middleware + json_log cost).
- Fault: forced 500 -> exactly one structured log line (event=request,
  status=500) + mocked-SDK capture_exception called once. NEVER a real DSN.
"""
from __future__ import annotations

import copy
import json
import logging
import statistics
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from turnstile_service.app import create_app
from turnstile_service.ratelimit import RateLimiter

ROOT = Path(__file__).resolve().parents[3]

STATUS_TOP_KEYS = {"ok", "commit", "uptime_sec", "warm", "engine_loaded",
                   "cache", "timings_ms"}
STATUS_CACHE_KEYS = {"entries", "byte_size", "hits", "misses", "hit_rate"}
STATUS_TIMINGS_KEYS = {"evaluate_median", "evaluate_p95", "source"}


def _client() -> TestClient:
    return TestClient(create_app(
        rate_limiter=RateLimiter(burst=1000, rate_per_sec=1000.0)))


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    call = json.loads(fence)
    call["id"] = f"call-metrics-{uuid.uuid4().hex[:8]}"
    return call


def _median_ms(samples: list[float]) -> float:
    return float(statistics.median(samples))


def test_metrics_200_keys_match_status_counters():
    """GET /metrics SHALL render Day-3's counters with cache/timings/jobs."""
    client = _client()
    call = _doc_example()
    assert client.post("/api/evaluate", json=call).status_code == 200
    assert client.post("/api/evaluate", json=call).status_code == 200
    res = client.get("/metrics")
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"
    body = res.json()
    assert set(body) == {"cache", "timings_ms", "jobs"}
    # Same counters /api/status reports, same values on the same state.
    status = client.get("/api/status").json()
    for key in STATUS_CACHE_KEYS:
        assert body["cache"][key] == status["cache"][key]
    assert body["timings_ms"] == status["timings_ms"]
    assert isinstance(body["jobs"]["active"], int)


def test_metrics_wall_under_50ms():
    """GET /metrics SHALL respond in <50ms (client-measured)."""
    client = _client()
    client.get("/metrics")  # warm route
    samples = []
    for _ in range(10):
        t0 = time.perf_counter()
        res = client.get("/metrics")
        samples.append((time.perf_counter() - t0) * 1000.0)
        assert res.status_code == 200
    wall = _median_ms(samples)
    assert wall < 50.0, f"/metrics median {wall:.1f}ms (>= 50ms budget)"


def test_status_shape_frozen_additive_only():
    """WHEN /metrics ships, /api/status bytes SHALL keep the Day-3 shape.

    Exact key sets (top + cache + timings) prove no existing route changed;
    /metrics is purely additive.
    """
    client = _client()
    base = _doc_example()
    for i in range(2):
        dup = copy.deepcopy(base)
        dup["id"] = f"call-frozen-{uuid.uuid4().hex[:8]}-{i}"
        assert client.post("/api/evaluate", json=dup).status_code == 200
    body = client.get("/api/status").json()
    assert set(body) == STATUS_TOP_KEYS
    assert set(body["cache"]) == STATUS_CACHE_KEYS
    assert set(body["timings_ms"]) == STATUS_TIMINGS_KEYS
    assert body["timings_ms"]["source"] == "eval"


def test_logging_overhead_median_under_5ms(monkeypatch):
    """The logging middleware SHALL add <5ms/request (median).

    Method: same HTTP path through TestClient with the request line on
    (TURNSTILE_REQUEST_LOG=1) vs off (=0); the TestClient stack cost cancels
    in the delta, leaving the middleware + json_log cost.
    """
    client = _client()
    client.get("/metrics")

    def _medians() -> float:
        samples = []
        for _ in range(25):
            t0 = time.perf_counter()
            assert client.get("/metrics").status_code == 200
            samples.append((time.perf_counter() - t0) * 1000.0)
        return _median_ms(samples)

    monkeypatch.setenv("TURNSTILE_REQUEST_LOG", "0")
    off = _medians()
    monkeypatch.setenv("TURNSTILE_REQUEST_LOG", "1")
    on = _medians()
    assert on - off < 5.0, f"logging overhead median {on - off:.2f}ms"


def test_forced_500_structured_log_and_sentry(monkeypatch, caplog):
    """WHEN the engine faults, the service SHALL log one structured line AND
    capture ONE Sentry event (mocked SDK -- never a real DSN in tests)."""
    sentry_sdk = pytest.importorskip("sentry_sdk")
    captured: list = []
    monkeypatch.setattr(sentry_sdk, "capture_exception",
                        lambda *a, **k: captured.append(True))
    import sys
    appmod = sys.modules["turnstile_service.app"]  # submodule, not the
    # package-level `app` object shadowing it in turnstile_service/__init__

    def _boom(*a, **k):
        raise RuntimeError("induced fault for Part C proof")

    monkeypatch.setattr(appmod, "run_calls", _boom)
    client = _client()
    with caplog.at_level(logging.INFO, logger="turnstile_service"):
        caplog.clear()
        res = client.post("/api/evaluate", json=_doc_example())
    assert res.status_code == 500
    assert res.json() == {"detail": "internal error while evaluating"}
    request_lines = []
    for record in caplog.records:
        if record.name != "turnstile_service":
            continue
        try:
            parsed = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict) and parsed.get("event") == "request":
            request_lines.append(parsed)
    assert len(request_lines) == 1, f"expected 1 request log line: {request_lines}"
    line = request_lines[0]
    assert line["method"] == "POST" and line["path"] == "/api/evaluate"
    assert line["status"] == 500 and line["duration_ms"] >= 0
    assert "ts" in line
    assert len(captured) == 1
