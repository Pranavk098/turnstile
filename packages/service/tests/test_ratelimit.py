"""Per-IP rate limiting (day-1 P0 #4): 429 before any engine run, no added latency.

Covers the EARS gate: WHEN a client exceeds the rate, the service SHALL
return 429 AND SHALL NOT invoke run_calls -- plus the ordering (rate check
before size checks), the latency budget (rate decision <5ms, allowed p95
sane), the untouched caps/determinism behavior, and the limiter unit
semantics. Every test builds a FRESH app with an explicit small limiter so
the burst trips deterministically and the module-level app's shared bucket
is never poisoned for the rest of the suite.
"""
from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from turnstile_service.app import MAX_BODY_BYTES, MAX_CALLS, create_app
from turnstile_service.cache import EvalCache
from turnstile_service.ratelimit import (
    DEFAULT_BURST,
    DEFAULT_RATE_PER_SEC,
    RateLimiter,
    client_ip,
    limiter_from_env,
)

ROOT = Path(__file__).resolve().parents[3]


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    return json.loads(fence)


def _fresh_client(burst: int, rate: float = 0.0) -> TestClient:
    """Isolated app: no refill by default so bursts trip deterministically."""
    return TestClient(create_app(rate_limiter=RateLimiter(burst=burst, rate_per_sec=rate)))


def _p95_ms(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)] * 1000.0


# -- limiter unit semantics ---------------------------------------------

def test_token_bucket_burst_then_refill_with_fake_clock():
    now = [1000.0]
    limiter = RateLimiter(burst=2, rate_per_sec=1.0, clock=lambda: now[0])
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False  # burst spent; denied consumes nothing
    assert limiter.allow("k") is False
    now[0] += 1.5  # 1.5 tokens back, capped at burst
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    now[0] += 100.0  # idle refills to full burst, never past it
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_buckets_are_per_key():
    limiter = RateLimiter(burst=1, rate_per_sec=0.0)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True  # a different key is unaffected


def test_client_ip_prefers_x_forwarded_for_first_ip():
    proxied = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.7, 70.41.3.18, 150.172.238.4"},
        client=SimpleNamespace(host="10.0.0.9"))
    assert client_ip(proxied) == "203.0.113.7"
    direct = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.9"))
    assert client_ip(direct) == "10.0.0.9"
    missing = SimpleNamespace(headers={"x-forwarded-for": "  "}, client=None)
    assert client_ip(missing) == "unknown"


def test_limiter_from_env_defaults_and_malformed(monkeypatch):
    monkeypatch.delenv("TURNSTILE_RL_BURST", raising=False)
    monkeypatch.delenv("TURNSTILE_RL_RATE", raising=False)
    limiter = limiter_from_env()
    assert (limiter.burst, limiter.rate_per_sec) == (DEFAULT_BURST, DEFAULT_RATE_PER_SEC)
    monkeypatch.setenv("TURNSTILE_RL_BURST", "7")
    monkeypatch.setenv("TURNSTILE_RL_RATE", "2.5")
    limiter = limiter_from_env()
    assert (limiter.burst, limiter.rate_per_sec) == (7, 2.5)
    monkeypatch.setenv("TURNSTILE_RL_BURST", "not-a-number")
    monkeypatch.setenv("TURNSTILE_RL_RATE", "-3")
    limiter = limiter_from_env()
    assert (limiter.burst, limiter.rate_per_sec) == (DEFAULT_BURST, DEFAULT_RATE_PER_SEC)


# -- EARS: 429 before any engine run -------------------------------------

def test_burst_n_plus_1_trips_429_on_evaluate():
    burst = 5
    client = _fresh_client(burst)
    call = _doc_example()
    statuses = [client.post("/api/evaluate", json=call).status_code
                for _ in range(burst + 1)]
    assert statuses == [200] * burst + [429]
    body = client.post("/api/evaluate", json=call).json()
    assert "detail" in body and "rate limit" in body["detail"]


def test_experiments_submit_shares_the_bucket_and_429s():
    client = _fresh_client(burst=3)
    call = _doc_example()
    variant = {"model_routing": {"route": "gpt-5-nano"}}
    for _ in range(3):
        assert client.post("/api/evaluate", json=call).status_code == 200
    # Burst spent via /api/evaluate: the submit path 429s without pricing.
    res = client.post("/api/experiments", json={"calls": [call], "variant": variant})
    assert res.status_code == 429
    assert "rate limit" in res.json()["detail"]


def test_429_path_never_touches_engine_cache_or_pricing(monkeypatch):
    """Denied requests return before body-read/caps/cache/engine: with the
    bucket spent, every downstream entry point may boom and the 429 stands."""
    import sys

    # NB: `turnstile_service.app` as an attribute is the FastAPI instance
    # (re-exported by __init__); the module itself lives in sys.modules.
    app_module = sys.modules["turnstile_service.app"]

    client = _fresh_client(burst=2)
    call = _doc_example()
    counts = {"run": 0}

    real_run_calls = app_module.run_calls

    def _counting(*args, **kwargs):
        counts["run"] += 1
        return real_run_calls(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_calls", _counting)
    assert client.post("/api/evaluate", json=call).status_code == 200
    assert client.post("/api/evaluate", json=call).status_code == 200
    runs_before_denial = counts["run"]

    def _boom(*args, **kwargs):
        raise AssertionError("denied request must not reach engine/cache/pricing")

    monkeypatch.setattr(app_module, "run_calls", _boom)
    monkeypatch.setattr(app_module, "_price_calls", _boom)
    monkeypatch.setattr(EvalCache, "get", _boom)
    denied = client.post("/api/evaluate", json=call)
    assert denied.status_code == 429
    assert counts["run"] == runs_before_denial  # engine ran zero extra times


def test_rate_check_runs_before_size_checks():
    """Ordering: a rate-spent client sees 429 even for an oversized body,
    while a fresh client sees the 413 for the same body."""
    spent = _fresh_client(burst=1)
    call = _doc_example()
    assert spent.post("/api/evaluate", json=call).status_code == 200
    big = {"calls": [call], "pad": "x" * (MAX_BODY_BYTES + 1)}
    assert spent.post("/api/evaluate", json=big).status_code == 429
    fresh = _fresh_client(1000, rate=1000.0)
    assert fresh.post("/api/evaluate", json=big).status_code == 413


def test_x_forwarded_for_keys_buckets_per_ip():
    client = _fresh_client(burst=1)
    call = _doc_example()
    headers_a = {"X-Forwarded-For": "203.0.113.7, 70.41.3.18"}
    assert client.post("/api/evaluate", json=call, headers=headers_a).status_code == 200
    assert client.post("/api/evaluate", json=call, headers=headers_a).status_code == 429
    headers_b = {"X-Forwarded-For": "198.51.100.9"}
    assert client.post("/api/evaluate", json=call, headers=headers_b).status_code == 200


# -- latency: no measurable cost on allowed requests ---------------------

def test_rate_decision_is_sub_5ms():
    limiter = RateLimiter(burst=10_000, rate_per_sec=10_000.0)
    worst_ms = 0.0
    for i in range(2000):
        start = time.perf_counter()
        assert limiter.allow(f"ip-{i % 50}") is True
        worst_ms = max(worst_ms, (time.perf_counter() - start) * 1000.0)
    assert worst_ms < 5.0


def test_allowed_requests_keep_charter_p95():
    """20 sequential allowed POSTs (1 miss + 19 cache hits): warm p95 stays
    inside the charter/day-1 <300ms budget -- the gate adds no latency."""
    client = _fresh_client(1000, rate=1000.0)
    call = _doc_example()
    elapsed: list[float] = []
    for _ in range(20):
        start = time.perf_counter()
        res = client.post("/api/evaluate", json=call)
        elapsed.append(time.perf_counter() - start)
        assert res.status_code == 200
    assert _p95_ms(elapsed) < 300.0


# -- caps + determinism untouched ----------------------------------------

def test_size_and_shape_gates_still_hold_with_limiter():
    client = _fresh_client(1000, rate=1000.0)
    call = _doc_example()
    big = {"calls": [call], "pad": "x" * (MAX_BODY_BYTES + 1)}
    assert client.post("/api/evaluate", json=big).status_code == 413
    many = []
    for i in range(MAX_CALLS + 1):
        dup = copy.deepcopy(call)
        dup["id"] = f"call-rl-flood-{i:03d}"
        many.append(dup)
    assert client.post("/api/evaluate", json={"calls": many}).status_code == 413
    bad = copy.deepcopy(call)
    bad["turns"][0]["llm"]["input_tokkens"] = bad["turns"][0]["llm"].pop("input_tokens")
    res = client.post("/api/evaluate", json=bad)
    assert res.status_code == 422
    assert "turns[0].llm.input_tokens" in res.json()["detail"]


def test_identical_allowed_posts_are_byte_identical():
    client = _fresh_client(1000, rate=1000.0)
    call = _doc_example()
    call["id"] = "call-rl-determinism-001"  # unique: no other test may cache it
    first = client.post("/api/evaluate", json=call)
    second = client.post("/api/evaluate", json=call)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
