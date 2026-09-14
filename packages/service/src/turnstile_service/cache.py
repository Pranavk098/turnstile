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
import threading
from collections import OrderedDict
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

    def get(self, key: str) -> bytes | None:
        """Cached response bytes, or None. Hits refresh recency."""
        with self._lock:
            body = self._entries.get(key)
            if body is None:
                return None
            self._entries.move_to_end(key)
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
            while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
                _, evicted = self._entries.popitem(last=False)
                self._bytes -= len(evicted)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def byte_size(self) -> int:
        """Current cached bytes (tests + capacity introspection)."""
        with self._lock:
            return self._bytes
