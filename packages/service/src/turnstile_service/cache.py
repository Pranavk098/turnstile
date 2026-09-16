"""Content-hash eval cache (PRD 03 §4.1): fast repeats, never stale.

``eval_key(call_json, rates_sha, baselines_sha)`` is sha-256 over the
normalized call plus the rate/baseline content identities -- the same file
bytes the reproducibility manifest records. A rate or baselines change is a
different key by construction, so a stale hit is impossible.

``EvalCache`` is an explicit byte-budgeted LRU (OrderedDict + lock):
functools.lru_cache cannot key dicts, and an unbounded dict would leak
memory on a public endpoint. Both entry count and total bytes are capped;
hits move to the most-recent end. Thread-safe for the service's sync
(threadpool) and async handlers alike.

Scope note: the cache stores whole evaluate responses keyed by the whole
request body. Fleet aggregates (margin replay, coverage roll-ups) are
functions of the full call set -- caching per-call fragments and
re-aggregating would reimplement run_calls' aggregation in the service
(engine impurity + drift risk). For the dominant single-call shape this
coincides with per-call caching exactly.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
import time
from collections import OrderedDict, deque
from typing import Any

#: Bounds: a public $0 endpoint must not become a memory sink. Bodies are
#: already capped at 1MB upstream; 8MB of cached responses is generous for
#: the demo shapes (a 1-call evaluate is ~10KB) while staying free-tier-safe.
MAX_EVAL_CACHE_ENTRIES = 128
MAX_EVAL_CACHE_BYTES = 8 * 1024 * 1024


def canonical_json(obj: Any) -> bytes:
    """Deterministic bytes for any JSON-shaped value (sorted keys, no
    whitespace): identical calls hash identically regardless of key order."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def eval_key(call_json: Any, rates_sha: str, baselines_sha: str) -> str:
    """sha-256 over ``rates_sha:baselines_sha:<canonical call>``."""
    digest = hashlib.sha256()
    digest.update(rates_sha.encode("utf-8"))
    digest.update(b":")
    digest.update(baselines_sha.encode("utf-8"))
    digest.update(b":")
    digest.update(canonical_json(call_json))
    return digest.hexdigest()


def request_key(calls: list, rates_sha: str, baselines_sha: str) -> str:
    """Cache key for one evaluate request: eval_key over the whole call list
    (fleet aggregates are set functions -- see module docstring)."""
    return eval_key(calls, rates_sha, baselines_sha)


class EvalCache:
    """Bounded LRU of response bytes, keyed by request key."""

    def __init__(self, *, max_entries: int = MAX_EVAL_CACHE_ENTRIES,
                 max_bytes: int = MAX_EVAL_CACHE_BYTES) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        # Day-3 observability (additive): hit/miss + timing counters.
        # Behavior of get/put/len/byte_size is unchanged.
        self._hits = 0
        self._misses = 0
        self._puts = 0
        self._evictions = 0
        self._total_hit_ns = 0
        self._total_miss_ns = 0
        self._latencies_ms: deque[float] = deque(maxlen=512)

    def get(self, key: str) -> bytes | None:
        """Cached response bytes, or None. Hits refresh recency."""
        start_ns = time.perf_counter_ns()
        with self._lock:
            body = self._entries.get(key)
            if body is None:
                elapsed_ns = time.perf_counter_ns() - start_ns
                self._misses += 1
                self._total_miss_ns += elapsed_ns
                self._latencies_ms.append(elapsed_ns / 1e6)
                return None
            self._entries.move_to_end(key)
            elapsed_ns = time.perf_counter_ns() - start_ns
            self._hits += 1
            self._total_hit_ns += elapsed_ns
            self._latencies_ms.append(elapsed_ns / 1e6)
            return body

    def put(self, key: str, body: bytes) -> bool:
        """Store response bytes; evict oldest-first past either cap. Bodies
        larger than the whole budget are refused (True/False = stored?)."""
        if len(body) > self._max_bytes:
            return False
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= len(old)
            self._entries[key] = body
            self._bytes += len(body)
            evicted = 0
            while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                _, evicted_body = self._entries.popitem(last=False)
                self._bytes -= len(evicted_body)
                evicted += 1
            self._puts += 1
            self._evictions += evicted
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def byte_size(self) -> int:
        """Current cached bytes (tests + capacity introspection)."""
        with self._lock:
            return self._bytes

    def stats(self) -> dict[str, Any]:
        """Day-3 observability snapshot: counters + hit-rate + median/p95
        over the bounded recent hit+miss latencies. Pure read; never runs
        the engine and never touches cached bytes."""
        with self._lock:
            hits = self._hits
            misses = self._misses
            puts = self._puts
            evictions = self._evictions
            entries = len(self._entries)
            byte_size = self._bytes
            latencies = list(self._latencies_ms)
        total = hits + misses
        hit_rate = (hits / total) if total else 0.0
        if not latencies:
            median_ms = 0.0
            p95_ms = 0.0
        elif len(latencies) == 1:
            median_ms = float(latencies[0])
            p95_ms = float(latencies[0])
        else:
            median_ms = float(statistics.median(latencies))
            try:
                p95_ms = float(statistics.quantiles(latencies, n=100)[94])
            except statistics.StatisticsError:
                ordered = sorted(latencies)
                idx = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95)))
                p95_ms = float(ordered[idx])
        return {
            "entries": entries,
            "byte_size": byte_size,
            "hits": hits,
            "misses": misses,
            "puts": puts,
            "evictions": evictions,
            "hit_rate": hit_rate,
            "median_ms": median_ms,
            "p95_ms": p95_ms,
        }
