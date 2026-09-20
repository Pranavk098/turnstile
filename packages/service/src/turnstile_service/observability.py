"""Day-5 Part C observability: structured logging + Sentry + /metrics reader.

Stdlib-only by construction: this module MUST import with zero new
dependencies so the $0 default path (no Sentry DSN, SDK absent) can never
break the service import. It reads Day-3's EXISTING counters only
(``EvalCache.stats()``, the bounded ``eval_latencies`` deque under its lock,
``JobStore.active_count()``) -- it defines no new counters and changes no
counter semantics (charter engine purity).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import statistics
import sys
from typing import Any

log = logging.getLogger("turnstile_service")


def ensure_log_handler() -> None:
    """Attach a single-line stdout handler iff the logger has none.

    Without this, ``log.info`` lines are silently dropped under servers
    (e.g. uvicorn) that configure only their own loggers: the root logger
    defaults to WARNING with no handler, so INFO records vanish. Idempotent.
    """
    if log.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    if log.level == logging.NOTSET:
        log.setLevel(logging.INFO)


def init_sentry() -> None:
    """Init Sentry iff ``SENTRY_DSN`` is set AND the SDK imports.

    DSN unset -> silent no-op (one debug line at startup max, never per
    request). SDK missing -> silent no-op too (belt and braces for the $0
    path: the service boots and serves identically either way).
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        log.debug("sentry disabled: SENTRY_DSN unset")
        return
    try:
        import sentry_sdk
    except ImportError:
        log.debug("sentry disabled: sentry_sdk not installed")
        return
    try:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0,
                        send_default_pii=False)
    except Exception:  # noqa: BLE001 -- observability never breaks boot
        log.debug("sentry init failed; continuing without Sentry")


def capture_current_exception() -> None:
    """Report the active exception to Sentry; never raises.

    Call only from inside an ``except`` block. Missing SDK / init failure /
    transport error all degrade to no-op -- observability never breaks eval.
    """
    try:
        import sentry_sdk
        sentry_sdk.capture_exception()
    except Exception:  # noqa: BLE001 -- observability never breaks eval
        pass


def json_log(event: str, **fields: Any) -> None:
    """One single-line JSON record on the ``turnstile_service`` logger.

    Shape: ``{ts, event, ...fields}``. Callers pass routing scalars only
    (method, path, status, duration_ms) -- NEVER request bodies, payload
    bytes, or PII (call ids are already opaque hashes).
    """
    payload = {"ts": datetime.datetime.now(
        datetime.timezone.utc).isoformat(), "event": event, **fields}
    log.info(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=True, default=str))


def _median_p95_ms(values: list[float]) -> tuple[float, float]:
    """Same stdlib median/p95 the Day-3 status path reports (no new math)."""
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), float(values[0])
    median = float(statistics.median(values))
    try:
        p95 = float(statistics.quantiles(values, n=100)[94])
    except statistics.StatisticsError:
        ordered = sorted(values)
        p95 = float(ordered[min(len(ordered) - 1,
                                max(0, int(len(ordered) * 0.95)))])
    return median, p95


def metrics_snapshot(app_state: Any) -> dict[str, Any]:
    """Read Day-3's existing counters into the ``/metrics`` payload.

    Pure read: cache stats + eval-latency deque (under its lock, same source
    label rule as ``/api/status``) + job-store active count. Never runs the
    engine, never touches cached bytes, never mutates a counter.
    """
    cache_stats = app_state.eval_cache.stats()
    with app_state.eval_latencies_lock:
        eval_samples = list(app_state.eval_latencies)
    if eval_samples:
        eval_median, eval_p95 = _median_p95_ms(eval_samples)
        source = "eval"
    else:
        eval_median = cache_stats["median_ms"]
        eval_p95 = cache_stats["p95_ms"]
        source = "cache_lookup"
    try:
        jobs_active = app_state.job_store.active_count()
    except Exception:  # noqa: BLE001 -- observability never breaks metrics
        jobs_active = 0
    return {
        "cache": {
            "entries": cache_stats["entries"],
            "byte_size": cache_stats["byte_size"],
            "hits": cache_stats["hits"],
            "misses": cache_stats["misses"],
            "puts": cache_stats["puts"],
            "evictions": cache_stats["evictions"],
            "hit_rate": cache_stats["hit_rate"],
            "median_ms": cache_stats["median_ms"],
            "p95_ms": cache_stats["p95_ms"],
        },
        "timings_ms": {
            "evaluate_median": eval_median,
            "evaluate_p95": eval_p95,
            "source": source,
        },
        "jobs": {"active": jobs_active},
    }
