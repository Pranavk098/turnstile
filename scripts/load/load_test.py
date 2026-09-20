"""Day-5 Part E load harness (P1 #6): sustained-throughput probe for POST /api/evaluate.

Stdlib + urllib ONLY (no k6/locust, no new dependency). Boots the REAL
uvicorn service as a subprocess, warms 5 requests, then drives two paths
separately and reports per-path {rps, median_ms, p95_ms, max_ms, errors}:

* miss path: unique call ids -> cache miss -> full engine run each time.
* hit path:  the doc-example body verbatim -> EvalCache hit.

Usage (all from the repo root)::

    uv run python scripts/load/load_test.py --smoke          # 10 reqs, 200s only
    uv run python scripts/load/load_test.py                  # fixed-count probe
    uv run python scripts/load/load_test.py --duration 60 --workers 4  # sustained
    uv run python scripts/load/load_test.py --target         # target derivation

Rules (work-split §7): numbers live in the run TRANSCRIPT and
``scripts/load/LIMITS.md``, NEVER as CI-gated constants. CI may run ONLY
``--smoke`` (asserts 200s, NO timing asserts -- timing is machine-relative).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CALL = (ROOT / "packages" / "service" / "src" / "turnstile_service"
                / "example_call.json")

# PERF.md measured baselines the target derives from (Day-3, MockBackend,
# Win11/20-CPU/py3.13.12): cold single-call eval min 62.3 / p50 62.9 /
# p95 66.1 / max 66.1 ms (n=6); cache-hit second POST 1.4 ms byte-identical.
# Quoted here so --target echoes the derivation; NOT a gate constant.
PERF_COLD_P95_MS = 66.1
PERF_HIT_MS = 1.4
SUSTAINED_P95_BUDGET_MS = 300.0


def machine_spec() -> str:
    return (f"{platform.platform()}, {os.cpu_count()} CPUs, "
            f"python {platform.python_version()}")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_healthy(base: str, deadline_s: float = 90.0) -> None:
    t0 = time.monotonic()
    last = "no attempt yet"
    while time.monotonic() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(base + "/health", timeout=5) as resp:
                if resp.status == 200:
                    return
                last = f"status {resp.status}"
        except Exception as exc:  # noqa: BLE001 -- boot probe, any error = retry
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise RuntimeError(f"server never healthy within {deadline_s}s ({last})")


def post_evaluate(base: str, body: bytes, timeout_s: float = 120.0,
                  opener: urllib.request.OpenerDirector | None = None,
                  ) -> tuple[int | None, float]:
    """One POST /api/evaluate -> (status or None on transport error, wall ms)."""
    req = urllib.request.Request(base + "/api/evaluate", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    t0 = time.perf_counter()
    try:
        if opener is not None:
            with opener.open(req, timeout=timeout_s) as resp:
                status: int | None = resp.status
        else:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception:  # noqa: BLE001 -- timeouts/refusals count as errors
        status = None
    return status, (time.perf_counter() - t0) * 1000.0


def summarize(latencies_ms: list[float]) -> tuple[float, float, float]:
    """(median, p95, max) over successful-request walls, stdlib only."""
    if not latencies_ms:
        return 0.0, 0.0, 0.0
    if len(latencies_ms) == 1:
        return float(latencies_ms[0]), float(latencies_ms[0]), float(latencies_ms[0])
    median = float(statistics.median(latencies_ms))
    try:
        p95 = float(statistics.quantiles(latencies_ms, n=100)[94])
    except statistics.StatisticsError:
        ordered = sorted(latencies_ms)
        p95 = float(ordered[min(len(ordered) - 1,
                                max(0, int(len(ordered) * 0.95)))])
    return median, p95, float(max(latencies_ms))


def run_phase(base: str, name: str, bodies: list[bytes], workers: int,
              opener: urllib.request.OpenerDirector | None = None) -> dict:
    """Fixed-count phase: workers x len(bodies) total POSTs; returns stats."""
    latencies: list[float] = []
    errors = 0
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(post_evaluate, base, body, 120.0, opener)
                   for body in bodies]
        for fut in concurrent.futures.as_completed(futures):
            status, ms = fut.result()
            if status == 200:
                latencies.append(ms)
            else:
                errors += 1
    wall_s = time.perf_counter() - t0
    median, p95, mx = summarize(latencies)
    return {"path": name, "n": len(bodies), "workers": workers,
            "wall_s": round(wall_s, 3),
            "rps": round(len(bodies) / wall_s, 2) if wall_s > 0 else 0.0,
            "median_ms": round(median, 2), "p95_ms": round(p95, 2),
            "max_ms": round(mx, 2), "errors": errors}


def run_sustained(base: str, body_factory, workers: int, duration_s: float,
                  opener: urllib.request.OpenerDirector | None = None) -> dict:
    """Sustained phase: each worker loops unique-id POSTs until the deadline."""
    latencies: list[float] = []
    lock = threading.Lock()
    stop_at = time.perf_counter() + duration_s
    counts = {"errors": 0}

    def worker(wid: int) -> int:
        n = 0
        while time.perf_counter() < stop_at:
            status, ms = post_evaluate(base, body_factory(wid, n), 120.0, opener)
            with lock:
                if status == 200:
                    latencies.append(ms)
                else:
                    counts["errors"] += 1
            n += 1
        return n

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        total = sum(pool.map(worker, range(workers)))
    wall_s = time.perf_counter() - t0
    median, p95, mx = summarize(latencies)
    return {"path": "miss-sustained", "n": total, "workers": workers,
            "wall_s": round(wall_s, 3),
            "rps": round(total / wall_s, 2) if wall_s > 0 else 0.0,
            "median_ms": round(median, 2), "p95_ms": round(p95, 2),
            "max_ms": round(mx, 2), "errors": counts["errors"]}


def print_stats(stats: dict) -> None:
    print(f"path={stats['path']} n={stats['n']} workers={stats['workers']} "
          f"wall_s={stats['wall_s']} rps={stats['rps']} "
          f"median_ms={stats['median_ms']} p95_ms={stats['p95_ms']} "
          f"max_ms={stats['max_ms']} errors={stats['errors']}", flush=True)


def boot_server(port: int, log_path: Path) -> subprocess.Popen:
    """Boot REAL uvicorn as a subprocess; returns the handle (caller kills it).

    Rate-limiter env is raised sky-high so the harness measures the engine +
    cache, not the demo token bucket (disclosed, load-config only -- the
    shipped defaults in ratelimit.py are untouched).
    """
    env = {**os.environ, "TURNSTILE_RL_BURST": "1000000",
           "TURNSTILE_RL_RATE": "1000000"}
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: PTH123
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "turnstile_service.app:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT)


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=15)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true",
                        help="10 requests, assert 200s only, no timing asserts")
    parser.add_argument("--target", action="store_true",
                        help="print the target derivation and exit")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--requests", type=int, default=25,
                        help="fixed-count requests per worker per path")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="sustained seconds for the miss path (0 = fixed-count only)")
    parser.add_argument("--port", type=int, default=0,
                        help="port (0 = ephemeral)")
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def target_text(warm_median_ms: float | None = None) -> str:
    lines = [
        "target derivation (PERF.md measured + live warm median):",
        f"  PERF.md cold single-call eval p95 = {PERF_COLD_P95_MS} ms (n=6) "
        f"[measured]",
        f"  PERF.md cache-hit second POST = {PERF_HIT_MS} ms [measured]",
        f"  Day-5 budget: sustained throughput at p95 < "
        f"{SUSTAINED_P95_BUDGET_MS:.0f} ms",
    ]
    if warm_median_ms is not None:
        lines.append(f"  live warm /api/evaluate median this run = "
                     f"{warm_median_ms:.2f} ms [measured]")
        headroom = SUSTAINED_P95_BUDGET_MS / max(warm_median_ms, 1e-9)
        lines.append(f"  headroom vs budget ~ {headroom:.1f}x on median; the "
                     f"sustained claim below is the highest RPS whose "
                     f"measured p95 stays < 300 ms.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.target and args.smoke:
        print("error: --target and --smoke are mutually exclusive")
        return 2
    if args.target:
        print(target_text())
        print(f"machine: {machine_spec()} seed={args.seed}")
        return 0

    base_call = json.loads(EXAMPLE_CALL.read_text(encoding="utf-8"))
    base_body = json.dumps(base_call).encode("utf-8")

    def miss_body(i: int) -> bytes:
        call = copy.deepcopy(base_call)
        call["id"] = f"load-{args.seed}-miss-{i:06d}"
        return json.dumps(call).encode("utf-8")

    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = Path(tempfile.gettempdir()) / f"turnstile-load-{port}.log"
    proc = boot_server(port, log_path)
    try:
        wait_healthy(base)
        # Warm: 5 sequential doc-example POSTs (1 miss + 4 hits); all must 200.
        warm_ms: list[float] = []
        for _ in range(5):
            status, ms = post_evaluate(base, base_body)
            if status != 200:
                print(f"warmup failed: status={status}; "
                      f"server log: {log_path}")
                return 1
            warm_ms.append(ms)
        warm_median = float(statistics.median(warm_ms))

        print(f"turnstile load test seed={args.seed}")
        print(f"machine: {machine_spec()}")
        print(f"server: real uvicorn subprocess on {base} "
              f"(log: {log_path})")
        print(f"warm: 5 requests, median_ms={warm_median:.2f} "
              f"(all 200) [measured]")
        print(target_text(warm_median))

        if args.smoke:
            # --smoke: 10 requests, 200s only, NO timing asserts.
            failures = 0
            for i in range(5):
                status, _ = post_evaluate(base, miss_body(10_000 + i))
                failures += status != 200
            for _ in range(5):
                status, _ = post_evaluate(base, base_body)
                failures += status != 200
            if failures:
                print(f"smoke FAILED: {failures}/10 non-200")
                return 1
            print("smoke ok: 10/10 requests returned 200 (no timing asserts)")
            return 0

        total = args.workers * args.requests
        miss_bodies = [miss_body(i) for i in range(total)]
        miss = run_phase(base, "miss", miss_bodies, args.workers)
        print_stats(miss)
        hit = run_phase(base, "hit", [base_body] * total, args.workers)
        print_stats(hit)

        if args.duration and args.duration > 0:
            counter = {"n": total}

            def factory(wid: int, k: int) -> bytes:
                counter["n"] += 1
                return miss_body(counter["n"])

            sustained = run_sustained(base, factory, args.workers,
                                      args.duration)
            print_stats(sustained)
            verdict = ("GREEN" if sustained["p95_ms"] < SUSTAINED_P95_BUDGET_MS
                       and sustained["errors"] == 0 else "OVER BUDGET")
            print(f"sustained claim: {sustained['rps']} RPS at p95 "
                  f"{sustained['p95_ms']} ms over {sustained['wall_s']} s "
                  f"(budget p95 < {SUSTAINED_P95_BUDGET_MS:.0f} ms): {verdict}")
        return 0
    finally:
        stop_server(proc)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
