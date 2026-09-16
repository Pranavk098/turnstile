"""Deployed live eval service (PRD 01): a thin FastAPI shell over the pure engine.

Architecture, enforced by construction:

* Read endpoints serve committed JSON bytes verbatim (``data.py``) -- no
  number is computed, reformatted, or stripped here. Provenance/tier notes
  reach the wire exactly as the pipeline wrote them.
* ``POST /api/evaluate`` calls exactly one engine entry point,
  ``turnstile_ingest.pipeline.run_calls``, with the repo's own rates and
  baselines. No business math lives in this module.
* Only the deterministic $0 path runs: ``run_calls`` prices, adjudicates,
  detects, and replays via the MockBackend mechanism. No code path here (or
  reachable from here) makes a paid API call -- there is no key handling, no
  HTTP client to a model provider, no GPU hook.
* Stateless: uploads are processed in-memory, never retained. DoS-bounded:
   per-IP token-bucket rate limit (HTTP 429 before any engine run) plus
   fixed body-size and call-count caps (HTTP 413 past them).

Run locally::

    uv run uvicorn turnstile_service.app:app --port 8000
"""
from __future__ import annotations

import json
import logging
import statistics
import subprocess
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from turnstile_schema import Baselines, VariantSpec, load_rates
from turnstile_ingest.adapter import DEFAULT_RATES_PATH, IngestError, load, parse_call
from turnstile_ingest.model import classify_file
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, run_calls
from turnstile_pricing import price_trace

from turnstile_service import data as committed
from turnstile_service.cache import EvalCache, request_key
from turnstile_service.jobs import JobStore, JobStoreFull, run_experiment_job
from turnstile_service.ratelimit import RateLimiter, client_ip, limiter_from_env

log = logging.getLogger("turnstile_service")

#: DoS bounds for the public $0 endpoint: fixed body cap + callset cap.
#: Past either, HTTP 413 -- never an engine run on an abusive payload.
MAX_BODY_BYTES = 1_000_000
MAX_CALLS = 25


@lru_cache(maxsize=1)
def _content_shas() -> tuple[str, str]:
    """sha-256 of the rates + baselines FILE bytes: the cache-invalidation
    identity (same bytes the reproducibility manifest records). Read once;
    the container image is immutable in prod."""
    import hashlib

    return (
        hashlib.sha256(Path(DEFAULT_RATES_PATH).read_bytes()).hexdigest(),
        hashlib.sha256(Path(DEFAULT_BASELINES_PATH).read_bytes()).hexdigest(),
    )


def _json_response_bytes(payload: dict) -> bytes:
    """One canonical serialization for evaluate responses: the bytes a cache
    miss sends are exactly the bytes a later hit replays."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


@lru_cache(maxsize=1)
def _engine():
    """The repo's own rates + baselines, loaded once (read-only, shared)."""
    rates = load_rates(DEFAULT_RATES_PATH)
    baselines = Baselines.model_validate(
        json.loads(Path(DEFAULT_BASELINES_PATH).read_text(encoding="utf-8")))
    return rates, baselines


def commit_sha() -> str:
    """Short commit SHA for /health: baked ``TURNSTILE_COMMIT`` wins (the
    container image sets it), then the host's own commit env (Render exposes
    ``RENDER_GIT_COMMIT``), else the checkout's git SHA, else "unknown"."""
    import os

    for env_key in ("TURNSTILE_COMMIT", "RENDER_GIT_COMMIT"):
        baked = os.environ.get(env_key)
        if baked:
            return baked
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[3],
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = (out.stdout or "").strip()
    return sha if out.returncode == 0 and sha else "unknown"


def _json_bytes_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _extract_calls(obj: Any) -> list | None:
    """Shared input shape for evaluate/experiments: one call, a callset, or
    a bare list. None when the shape is wrong (caller answers 422)."""
    kind = classify_file(obj)
    if kind == "call":
        return [obj]
    if kind == "callset":
        return obj["calls"] if isinstance(obj, dict) else obj
    return None


def _price_calls(calls: list, rates) -> list:
    """Validate + load + price each call (existing entry points only).

    Raises IngestError naming the bad field -- the endpoint turns it into
    422, never 500. No detect/replay here: experiments price synchronously
    (fast) and replay asynchronously.
    """
    priced = []
    for obj in calls:
        call = parse_call(obj)
        priced.append(price_trace(load(call, rates=rates), rates))
    return priced


def _content_length_exceeds(headers) -> bool:
    """True when a present, well-formed Content-Length already exceeds the cap.

    Checked before the body is read (early 413 without buffering). Absent,
    malformed, or non-positive values fall through to the post-read length
    check -- Content-Length can be missing or wrong under chunked encoding,
    so both checks stay (defense in depth, same 413).
    """
    raw = headers.get("content-length")
    if raw is None:
        return False
    try:
        return int(raw.strip()) > MAX_BODY_BYTES
    except ValueError:
        return False


def _median_p95_ms(values: list[float]) -> tuple[float, float]:
    """Median/p95 over wall-ms samples with stdlib only. Empty -> 0.0s
    (no data yet); single sample -> that value for both."""
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), float(values[0])
    median = float(statistics.median(values))
    try:
        p95 = float(statistics.quantiles(values, n=100)[94])
    except statistics.StatisticsError:
        ordered = sorted(values)
        idx = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95)))
        p95 = float(ordered[idx])
    return median, p95


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Day-3 P1 #7: preload the committed fleet bytes once at boot
    (read-only snapshot; no engine run — the status path never touches the
    engine either way). Read endpoints serve the snapshot when present and
    fall back to disk reads otherwise, so app construction without lifespan
    (tests, import) behaves exactly as before."""
    committed.warm()
    yield


def create_app(rate_limiter: RateLimiter | None = None) -> FastAPI:
    app = FastAPI(title="Turnstile demo eval service", version="1.0.0",
                  lifespan=_lifespan)
    app.state.eval_cache = EvalCache()
    app.state.job_store = JobStore()
    app.state.rate_limiter = rate_limiter or limiter_from_env()
    app.state.start_monotonic = time.monotonic()
    # Day-3 observability: bounded wall-ms samples of /api/evaluate handler
    # time (hit + miss). deque.append is atomic under the GIL; the lock
    # makes read-copy vs append deterministic for status snapshots.
    app.state.eval_latencies: deque[float] = deque(maxlen=512)
    app.state.eval_latencies_lock = threading.Lock()
    # P1 #7: compress responses >=1KB; adds no measurable latency to small
    # JSON and cuts fleet/detail payloads on slow links.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def cache_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        """P1 #7 cache policy: mutating + status = no-store; API reads =
        short public cache; committed static bytes = longer public cache."""
        response = await call_next(request)
        path = request.url.path
        if request.method == "POST" or path == "/api/status":
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/api/") or path == "/health":
            response.headers["Cache-Control"] = "public, max-age=60"
        elif (path.startswith("/sample/") or path.endswith(
                (".json", ".html", ".css", ".js", ".png", ".woff2"))):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    def _rate_limited(request: Request) -> JSONResponse | None:
        """Per-IP token-bucket gate. FIRST in every mutating handler: a 429
        here returns before any body read, size check, cache lookup, or
        engine run."""
        limiter: RateLimiter = request.app.state.rate_limiter
        if limiter.allow(client_ip(request)):
            return None
        return _json_bytes_error(
            429, f"rate limit exceeded: burst is {limiter.burst} requests "
                 f"(refill {limiter.rate_per_sec:g}/sec)")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "commit": commit_sha()}

    @app.get("/api/status")
    def api_status(request: Request) -> dict[str, Any]:
        """P1 #8 lightweight status for the Day-7 QA gate: uptime, commit,
        warm/cold. No engine run, no PII, no request-body read."""
        start: float = request.app.state.start_monotonic
        cache_stats = request.app.state.eval_cache.stats()
        with request.app.state.eval_latencies_lock:
            eval_samples = list(request.app.state.eval_latencies)
        if eval_samples:
            eval_median, eval_p95 = _median_p95_ms(eval_samples)
        else:
            # No evaluate traffic yet: fall back to cache-lookup timings so
            # median/p95 are still numbers without ever running the engine.
            eval_median, eval_p95 = (
                cache_stats["median_ms"], cache_stats["p95_ms"])
        return {
            "ok": True,
            "commit": commit_sha(),
            "uptime_sec": round(time.monotonic() - start, 1),
            "warm": True,
            "engine_loaded": _engine.cache_info().currsize > 0,
            "cache": {
                "entries": cache_stats["entries"],
                "byte_size": cache_stats["byte_size"],
                "hits": cache_stats["hits"],
                "misses": cache_stats["misses"],
                "hit_rate": cache_stats["hit_rate"],
            },
            "timings_ms": {
                "evaluate_median": eval_median,
                "evaluate_p95": eval_p95,
            },
        }

    for name in committed.READ_ENDPOINTS:
        _register_sample_route(app, name)

    @app.get("/api/ingest")
    def api_ingest() -> Response:
        if not committed.INGEST_ARTIFACT.exists():
            return _json_bytes_error(404, "ingest artifact not built")
        return Response(content=committed.read_ingest_artifact(),
                        media_type="application/json")

    @app.get("/api/example")
    def api_example() -> Response:
        return Response(content=committed.read_example_call(),
                        media_type="application/json")

    @app.get("/api/calls/{call_id}")
    def api_call(call_id: str) -> Response:
        path = committed.call_detail_path(call_id)
        if path is None:
            return _json_bytes_error(404, f"unknown call {call_id!r}")
        return Response(content=path.read_bytes(), media_type="application/json")

    @app.post("/api/evaluate")
    async def api_evaluate(request: Request) -> Response:
        denied = _rate_limited(request)
        if denied is not None:
            return denied
        # Day-3: full-handler wall clock (body read + parse + key + cache or
        # engine + serialize), so timings_ms.evaluate_* is the whole serve
        # cost, not just the cache-lookup slice. Errors (429/413/422/500)
        # return before/around it and record nothing.
        t0 = time.perf_counter()

        def _record_eval_ms() -> None:
            """One wall-ms sample of handler time (hit or miss)."""
            dt_ms = (time.perf_counter() - t0) * 1000.0
            try:
                with request.app.state.eval_latencies_lock:
                    request.app.state.eval_latencies.append(dt_ms)
            except Exception:  # noqa: BLE001 -- observability never breaks eval
                pass

        declared = request.headers.get("content-length")
        if _content_length_exceeds(request.headers):
            return _json_bytes_error(
                413, f"body is {declared.strip()} bytes; limit is {MAX_BODY_BYTES}")
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return _json_bytes_error(
                413, f"body is {len(raw)} bytes; limit is {MAX_BODY_BYTES}")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            return _json_bytes_error(422, f"invalid JSON: {exc}")
        calls = _extract_calls(obj)
        if calls is None:
            return _json_bytes_error(
                422, "expected one call object (with 'id'), "
                     "a {\"calls\": [...]} callset, or a bare list "
                     "-- see docs/INGEST.md")
        if not isinstance(calls, list) or not calls:
            return _json_bytes_error(422, "'calls' must be a non-empty list")
        if len(calls) > MAX_CALLS:
            return _json_bytes_error(
                413, f"{len(calls)} calls; limit is {MAX_CALLS}")
        rates, baselines = _engine()
        n = len(calls)
        cache_key = request_key(calls, *_content_shas())
        cached = request.app.state.eval_cache.get(cache_key)
        if cached is not None:
            _record_eval_ms()
            return Response(content=cached, media_type="application/json")
        try:
            artifact, details = run_calls(
                calls, rates, baselines,
                label=f"api evaluate ({n} call(s))", sample=False)
        except IngestError as exc:
            # Malformed user input: loud 422 with the engine's field path,
            # never a 500.
            return _json_bytes_error(422, str(exc))
        except Exception:  # noqa: BLE001 -- genuine server fault: log + 500
            log.exception("evaluate failed on %d call(s)", n)
            return _json_bytes_error(500, "internal error while evaluating")
        # Additive-only shape: the run_calls artifact verbatim, plus the
        # already-computed per-call detail payloads (trace, span_costs,
        # verdict, findings, _provenance) keyed by detail filename, so the
        # front-end can drill down with the existing detail renderer.
        body = _json_response_bytes({**artifact, "details": details})
        request.app.state.eval_cache.put(cache_key, body)
        _record_eval_ms()
        return Response(content=body, media_type="application/json")

    @app.post("/api/experiments", status_code=202)
    async def api_experiments_submit(request: Request) -> Response:
        """Queue a gated MockBackend variant sweep; returns immediately.

        Body: ``{"calls": [...], "variant": VariantSpec}`` -- same call caps
        as /api/evaluate. Validation (and pricing) happens synchronously so
        bad input still fails loud with 422/413; only the replay runs async.
        """
        denied = _rate_limited(request)
        if denied is not None:
            return denied
        declared = request.headers.get("content-length")
        if _content_length_exceeds(request.headers):
            return _json_bytes_error(
                413, f"body is {declared.strip()} bytes; limit is {MAX_BODY_BYTES}")
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return _json_bytes_error(
                413, f"body is {len(raw)} bytes; limit is {MAX_BODY_BYTES}")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            return _json_bytes_error(422, f"invalid JSON: {exc}")
        if not isinstance(obj, dict):
            return _json_bytes_error(
                422, "expected {\"calls\": [...], \"variant\": {...}}")
        calls = _extract_calls(obj.get("calls", obj))
        if not isinstance(calls, list) or not calls:
            return _json_bytes_error(422, "'calls' must be a non-empty list")
        if len(calls) > MAX_CALLS:
            return _json_bytes_error(
                413, f"{len(calls)} calls; limit is {MAX_CALLS}")
        try:
            variant = VariantSpec.model_validate(obj.get("variant", {}))
        except Exception as exc:  # noqa: BLE001 -- pydantic ValidationError -> loud 422
            return _json_bytes_error(422, f"invalid variant: {exc}")
        rates, _baselines = _engine()
        try:
            priced = _price_calls(calls, rates)
        except IngestError as exc:
            return _json_bytes_error(422, str(exc))
        except Exception:  # noqa: BLE001 -- genuine server fault
            log.exception("experiment pricing failed on %d call(s)", len(calls))
            return _json_bytes_error(500, "internal error while evaluating")
        rates_sha, baselines_sha = _content_shas()
        store: JobStore = request.app.state.job_store
        try:
            job = store.submit(
                variant=variant.model_dump(mode="json", exclude_none=True),
                n_calls=len(calls),
                rates_sha=rates_sha,
                baselines_sha=baselines_sha,
                run=lambda: run_experiment_job(priced, variant),
            )
        except JobStoreFull as exc:
            return _json_bytes_error(429, str(exc))
        return JSONResponse(status_code=202,
                            content={"job_id": job.job_id, "status": job.status})

    @app.get("/api/experiments/{job_id}")
    async def api_experiments_poll(job_id: str, request: Request) -> Response:
        """One job's lifecycle: queued|running|done|error. Unknown or evicted
        ids (TTL/store caps make state ephemeral) read as 404."""
        store: JobStore = request.app.state.job_store
        job = store.get(job_id)
        if job is None:
            return _json_bytes_error(404, f"unknown or evicted job {job_id!r}")
        return JSONResponse(content=job.public())

    # Single origin: the dashboard (HTML + its committed sample/*.json) is
    # served from the same app, so there is no CORS surface. Mounted LAST so
    # /api/* and /health keep precedence over static files.
    app.mount("/", StaticFiles(directory=str(committed.DASHBOARD_DIR), html=True),
              name="dashboard")
    return app


def _register_sample_route(app: FastAPI, name: str) -> None:
    filename = committed.READ_ENDPOINTS[name]

    @app.get(f"/api/{name}", name=f"api_{name}")
    def api_sample() -> Response:
        return Response(content=committed.read_sample(filename),
                        media_type="application/json")


app = create_app()
