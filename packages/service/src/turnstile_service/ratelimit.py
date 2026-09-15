"""Per-IP token-bucket rate limiting for the public $0 edge (day-1 P0 #4).

Placed FIRST in the request path -- before body reads, size checks, cache
lookups, and any engine call -- so an abusive client gets HTTP 429 without
costing the server an engine run. Allowed-request overhead is one dict
lookup plus float arithmetic under a single lock (microseconds; budget
<5ms).

Config (env, read once per ``limiter_from_env`` call)::

    TURNSTILE_RL_BURST  max rapid requests per IP before 429s (default 60)
    TURNSTILE_RL_RATE   sustained tokens/sec refilled per IP (default 1.0)

One shared bucket per client IP covers both ``POST /api/evaluate`` and
``POST /api/experiments``: abuse of either endpoint consumes the same
tokens. Buckets live in memory only (stateless service, never persisted)
and the tracker is bounded (oldest-idle IP evicted past the cap) so the
limiter itself cannot become a memory sink.

$0/engine-purity note: this module does no I/O, imports no engine code,
and makes no network calls -- pure token math plus header parsing.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Callable

#: Sane defaults, documented for operators: a 60-request burst absorbs real
#: demo pastes plus the repo's own test-suite traffic from one IP, while 1
#: token/sec sustained still throttles floods to a trickle the $0 tier can
#: serve. Tighten via env on the host; never loosen to go green.
DEFAULT_BURST = 60
DEFAULT_RATE_PER_SEC = 1.0

#: Env knobs (see module docstring).
ENV_BURST = "TURNSTILE_RL_BURST"
ENV_RATE = "TURNSTILE_RL_RATE"

#: Bound on tracked IPs: public traffic must not grow this dict forever.
MAX_TRACKED_IPS = 4096


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= 1 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if value >= 0.0 else default


class RateLimiter:
    """In-memory per-key token bucket. ``allow`` is the only hot path."""

    def __init__(
        self,
        *,
        burst: int = DEFAULT_BURST,
        rate_per_sec: float = DEFAULT_RATE_PER_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._burst = max(1, int(burst))
        self._rate = max(0.0, float(rate_per_sec))
        self._clock = clock
        self._lock = threading.Lock()
        # key -> [tokens: float, updated_at: float]; OrderedDict for
        # oldest-idle-first eviction past MAX_TRACKED_IPS.
        self._buckets: OrderedDict[str, list] = OrderedDict()

    @property
    def burst(self) -> int:
        return self._burst

    @property
    def rate_per_sec(self) -> float:
        return self._rate

    def allow(self, key: str) -> bool:
        """Consume one token for ``key``. True = allowed; False = over limit
        (no token consumed, so the client keeps 429ing until refill)."""
        now = self._clock()
        with self._lock:
            entry = self._buckets.get(key)
            if entry is None:
                entry = [float(self._burst), now]
                self._buckets[key] = entry
            else:
                # Refill since last touch, capped at burst; refresh recency.
                entry[0] = min(
                    float(self._burst),
                    entry[0] + (now - entry[1]) * self._rate,
                )
                entry[1] = now
                self._buckets.move_to_end(key)
            if entry[0] >= 1.0:
                entry[0] -= 1.0
                allowed = True
            else:
                allowed = False
            while len(self._buckets) > MAX_TRACKED_IPS:
                self._buckets.popitem(last=False)
            return allowed

    def reset(self) -> None:
        """Drop all buckets (tests / operator reset)."""
        with self._lock:
            self._buckets.clear()


def limiter_from_env(
    clock: Callable[[], float] = time.monotonic,
) -> RateLimiter:
    """Build a limiter from ``TURNSTILE_RL_BURST``/``TURNSTILE_RL_RATE``,
    falling back to the documented defaults on absent/malformed values."""
    return RateLimiter(
        burst=_env_int(ENV_BURST, DEFAULT_BURST),
        rate_per_sec=_env_float(ENV_RATE, DEFAULT_RATE_PER_SEC),
        clock=clock,
    )


def client_ip(request) -> str:
    """Client identity for rate buckets: first IP in ``X-Forwarded-For``
    (host proxies sit in front in prod), else the peer ``client.host``."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    peer = getattr(request, "client", None)
    host = getattr(peer, "host", None)
    return host or "unknown"


__all__ = [
    "DEFAULT_BURST",
    "DEFAULT_RATE_PER_SEC",
    "ENV_BURST",
    "ENV_RATE",
    "MAX_TRACKED_IPS",
    "RateLimiter",
    "client_ip",
    "limiter_from_env",
]
