"""Eval cache: key stability, auto-invalidation, bounds, byte-identity.

P0 verify: identical input -> same key; a rates-SHA change -> different key;
LRU evicts at cap. P1 verify lives in test_evaluate.py (hit skips the engine
via a spy; parity with the CLI still holds).
"""
from __future__ import annotations

from turnstile_service.cache import EvalCache, eval_key


def test_eval_key_stable_and_order_insensitive():
    call = {"id": "c1", "b": [1, 2], "a": "x"}
    shuffled = {"a": "x", "id": "c1", "b": [1, 2]}
    assert eval_key(call, "ratesA", "baseA") == eval_key(shuffled, "ratesA", "baseA")
    assert len(eval_key(call, "ratesA", "baseA")) == 64  # sha-256 hex


def test_eval_key_invalidates_on_rates_or_baselines_change():
    call = {"id": "c1"}
    base = eval_key(call, "ratesA", "baseA")
    assert eval_key(call, "ratesB", "baseA") != base
    assert eval_key(call, "ratesA", "baseB") != base
    assert eval_key({"id": "c2"}, "ratesA", "baseA") != base


def test_lru_evicts_oldest_at_entry_cap():
    cache = EvalCache(max_entries=2, max_bytes=10**6)
    assert cache.put("a", b"1") is True
    assert cache.put("b", b"2") is True
    assert cache.get("a") == b"1"  # refreshes recency: b is now oldest
    assert cache.put("c", b"3") is True
    assert cache.get("b") is None  # evicted
    assert cache.get("a") == b"1" and cache.get("c") == b"3"
    assert len(cache) == 2


def test_lru_evicts_past_byte_budget_and_refuses_oversize():
    cache = EvalCache(max_entries=100, max_bytes=4)
    assert cache.put("a", b"12") is True
    assert cache.byte_size == 2
    assert cache.put("b", b"345") is True  # evicts "a" to fit
    assert cache.get("a") is None
    assert cache.get("b") == b"345"
    assert cache.put("huge", b"12345") is False  # bigger than the whole budget
    assert cache.get("huge") is None


def test_cache_overwrite_replaces_bytes():
    cache = EvalCache()
    assert cache.put("a", b"12") is True
    assert cache.put("a", b"1234") is True
    assert cache.get("a") == b"1234"
    assert cache.byte_size == 4
    assert cache.get("missing") is None
