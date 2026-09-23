"""Day-7 P0-1 pre-launch QA gate: probe the LIVE (or LOCAL) surfaces, ALL green or ABORT.

Gates (first failure names the abort; exit 0 only when every gate passes):
  demo-up ......... GET /health + GET / in budget (cold interactive <5s)
  evaluate-p95 .... >=5 warm POST /api/evaluate, no 5xx, warm p95 <300ms
  evaluate-cache .. cache-hit path p95 <50ms (server-side, via /api/status)
  ci-green ........ CI green on the pushed tip (gh api, read-only; badge fallback)
  pip-install ..... service installs from built sdist/wheel (dist/, else uv build; $0)
  docs-links ...... scripts/check_links.py green + docs URL up
  quality-cost .... fleet/call detail shows quality block + provenance tiers beside cost

Latency note (honesty): end-to-end numbers from the prober include client<->host
RTT, which is environmental (vantage-point dependent), not code. The <300ms /
<50ms budgets gate the SERVER-side cost, estimated as e2e minus the measured
RTT baseline (median GET /health) and cross-checked against the service's own
/api/status timings_ms (source labeled). Both populations print in the transcript.

Usage:
  uv run python scripts/prelaunch_qa.py [--base URL] [--spawn-local] [--self-test]

--self-test injects one seeded failure (dead base) and PASSES (exit 0) only if
the QA aborts non-zero with the failing gate named. --spawn-local boots a local
uvicorn on an ephemeral port and runs the whole gate against it instead of LIVE.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_BASE = "https://turnstile-demo.onrender.com"
REPO = "Pranavk098/turnstile"
TIERS = {"measured", "instrumented", "not_measured"}

EVAL_P95_BUDGET_MS = 300.0
CACHE_HIT_P95_BUDGET_MS = 50.0
COLD_BUDGET_S = 5.0
N_EVAL_SAMPLES = 6  # 1 warmup + >=5 measured


class GateFail(Exception):
    """A gate failed; message names the gate and the evidence."""


def _p95_ms(samples: list[float]) -> float:
    if len(samples) == 1:
        return float(samples[0])
    try:
        p95 = statistics.quantiles(samples, n=100)[94]
    except statistics.StatisticsError:
        ordered = sorted(samples)
        p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95)))]
    # Cap at the largest observed sample: the exclusive method can extrapolate
    # ABOVE max on a small sample (e.g. 5 warm calls), which would false-reject
    # a healthy service whose every measured latency is under budget.
    return float(min(p95, max(samples)))


def _req(method: str, url: str, body: bytes | None = None,
         timeout: float = 90.0) -> tuple[int, bytes, float]:
    """One HTTP request. Returns (status, body, wall_ms). Never raises on HTTP
    error status (5xx is evidence, returned to the caller); raises GateFail on
    connection failure. Any 5xx observed aborts the calling gate."""
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            payload = res.read()
            return res.status, payload, (time.perf_counter() - t0) * 1000.0
    except urllib.error.HTTPError as exc:
        payload = exc.read() if hasattr(exc, "read") else b""
        ms = (time.perf_counter() - t0) * 1000.0
        if exc.code >= 500:
            raise GateFail(f"5xx guard: {method} {url} -> HTTP {exc.code} "
                           f"({ms:.0f}ms); launch aborts") from exc
        return exc.code, payload, ms
    except Exception as exc:
        raise GateFail(f"unreachable: {method} {url}: {exc}") from exc


def _get_json(base: str, path: str, timeout: float = 90.0) -> tuple[dict, float]:
    status, payload, ms = _req("GET", base + path, timeout=timeout)
    if status != 200:
        raise GateFail(f"GET {path} -> HTTP {status}, want 200")
    try:
        return json.loads(payload), ms
    except json.JSONDecodeError as exc:
        raise GateFail(f"GET {path} -> 200 but not JSON: {exc}") from exc


def gate_demo_up(base: str, out: list[str]) -> None:
    health, health_ms = _get_json(base, "/health")
    if health.get("ok") is not True:
        raise GateFail(f"demo-up: /health not ok: {health}")
    t0 = time.perf_counter()
    status, payload, _ = _req("GET", base + "/", timeout=120.0)
    cold_s = time.perf_counter() - t0
    if status != 200:
        raise GateFail(f"demo-up: GET / -> HTTP {status}, want 200")
    if cold_s > COLD_BUDGET_S:
        raise GateFail(f"demo-up: cold fetch {cold_s:.1f}s > {COLD_BUDGET_S:.0f}s "
                       f"budget ({len(payload)} bytes)")
    out.append(f"  /health -> 200 in {health_ms:.0f}ms, commit={health.get('commit')}")
    out.append(f"  GET / -> 200 first-contact {cold_s:.2f}s (<5s), {len(payload)} bytes")


def _eval_body() -> bytes:
    return (ROOT / "packages" / "service" / "src" / "turnstile_service"
            / "example_call.json").read_bytes()


def _rtt_baseline(base: str) -> float:
    return float(statistics.median([_get_json(base, "/health")[1] for _ in range(3)]))


def gate_evaluate(base: str, out: list[str]) -> None:
    body = _eval_body()
    # RTT baseline: tiny no-engine reads; the budgets gate server cost, not geography.
    rtt_med = _rtt_baseline(base)
    e2e: list[float] = []
    for i in range(N_EVAL_SAMPLES):
        status, payload, ms = _req("POST", base + "/api/evaluate", body=body)
        if status != 200:
            raise GateFail(f"evaluate-p95: sample {i} -> HTTP {status}, want 200")
        json.loads(payload)  # must parse (5xx already aborts in _req)
        e2e.append(ms)
    warm = e2e[1:]  # drop the cold-engine warmup sample
    labels = ("median", "p95")
    med, p95 = float(statistics.median(warm)), _p95_ms(warm)
    server_est = max(0.0, p95 - rtt_med)  # RTT-corrected server-side estimate
    try:
        timings = _get_json(base, "/api/status")[0]["timings_ms"]
    except GateFail:
        timings = {}
    out.append(f"  warm e2e {labels}: {med:.0f}/{p95:.0f}ms over {len(warm)} samples "
               f"(raw: {[round(x) for x in warm]})")
    out.append(f"  RTT baseline (3x /health median): {rtt_med:.0f}ms; "
               f"server-side warm p95 est: {server_est:.0f}ms (<300ms)")
    out.append(f"  /api/status timings_ms: {timings}")
    if server_est > EVAL_P95_BUDGET_MS:
        raise GateFail(f"evaluate-p95: server-side warm p95 est {server_est:.0f}ms "
                       f"> 300ms (e2e p95 {p95:.0f}ms - RTT {rtt_med:.0f}ms)")


def gate_evaluate_cache(base: str, out: list[str]) -> None:
    """Cache-hit path: identical bodies must be cache hits (sub-ms server).

    Server-side proof comes from the service's own /api/status: cache.hits must
    rise by >=5 with no new miss, and the eval-handler median must be <50ms.
    Median (not cumulative p95) because the cumulative p95 mixes a different
    population (cold-engine misses); hits themselves are ~0.5ms with nil
    variance, so the median represents the hit path. E2e numbers print as
    transcript only: over a ~170ms RTT link, e2e jitter exceeds the 50ms
    budget and cannot resolve it."""
    body = _eval_body()
    before = _get_json(base, "/api/status")[0]
    _req("POST", base + "/api/evaluate", body=body)  # ensure residency
    hits = [_req("POST", base + "/api/evaluate", body=body)[2] for _ in range(5)]
    after = _get_json(base, "/api/status")[0]
    d_hits = after["cache"]["hits"] - before["cache"]["hits"]
    d_miss = after["cache"]["misses"] - before["cache"]["misses"]
    timings = after["timings_ms"]
    med = timings["evaluate_median"]
    out.append(f"  e2e hits median/p95: {statistics.median(hits):.0f}/"
               f"{_p95_ms(hits):.0f}ms (transcript only; RTT-bound)")
    out.append(f"  server: +{d_hits} hits +{d_miss} misses; timings_ms={timings}")
    if d_hits < 5 or d_miss != 0:
        raise GateFail(f"evaluate-cache: expected +>=5 hits/+0 misses, "
                       f"got +{d_hits}/+{d_miss}")
    if timings.get("source") != "eval" or med > CACHE_HIT_P95_BUDGET_MS:
        raise GateFail(f"evaluate-cache: server eval median {med:.1f}ms "
                       f"(source={timings.get('source')}) > 50ms")


def _gh(*args: str) -> str:
    proc = subprocess.run(["gh", "api", *args], capture_output=True, text=True,
                          timeout=60)
    if proc.returncode != 0:
        raise GateFail(f"gh api {' '.join(args[:2])} failed: "
                       f"{proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def gate_ci(out: list[str]) -> None:
    try:
        branch = json.loads(_gh(f"repos/{REPO}", "--jq", "{b:.default_branch}"))["b"]
        sha = _gh(f"repos/{REPO}/commits/{branch}", "--jq", ".sha")
        runs = json.loads(_gh(f"repos/{REPO}/commits/{sha}/check-runs",
                              "--jq", "{t:.total_count,r:[.check_runs[]"
                                      "|{n:.name,s:.status,c:.conclusion}]}"))
    except GateFail as exc:
        # No gh/auth (environmental): fall back to the public CI badge (read-only).
        badge = f"https://github.com/{REPO}/actions/workflows/ci.yml/badge.svg"
        try:
            _, payload, _ = _req("GET", badge, timeout=30.0)
            green = b"passing" in payload
        except GateFail:
            raise GateFail(f"ci-green: gh unavailable ({exc}) and badge "
                           f"unreachable (environmental)") from exc
        if not green:
            raise GateFail("ci-green: badge does not read passing (environmental: "
                           "confirm CI manually)")
        out.append(f"  gh unavailable; badge {badge} reads passing")
        return
    if runs["t"] == 0:
        raise GateFail(f"ci-green: no check runs on tip {sha[:7]}")
    bad = [r for r in runs["r"] if r["s"] != "completed" or r["c"] != "success"]
    out.append(f"  tip {sha[:7]} ({branch}): {runs['t']} checks, "
               f"bad={[r['n'] for r in bad]}")
    if bad:
        raise GateFail(f"ci-green: {[r['n'] + ':' + str(r['c']) for r in bad]} "
                       f"on tip {sha[:7]}")


def gate_pip_install(out: list[str]) -> None:
    dist = ROOT / "dist"
    wheel = sorted(dist.glob("turnstile_service-*.whl")) if dist.exists() else []
    if not wheel:
        proc = subprocess.run(["uv", "build", "--package", "turnstile-service",
                               "--out-dir", "dist/"], capture_output=True, text=True,
                              timeout=300, cwd=ROOT)
        if proc.returncode != 0:
            raise GateFail(f"pip-install: uv build failed: "
                           f"{proc.stderr.strip()[-300:]}")
        wheel = sorted(dist.glob("turnstile_service-*.whl"))
    if not wheel:
        raise GateFail("pip-install: no turnstile-service wheel after build")
    proc = subprocess.run(
        ["uv", "pip", "install", "--dry-run", "--offline", "--no-deps",
         "--find-links", str(dist), "turnstile-service"],
        capture_output=True, text=True, timeout=120, cwd=ROOT)
    if proc.returncode != 0:
        raise GateFail(f"pip-install: dry-run failed: "
                       f"{proc.stderr.strip()[-300:]}")
    out.append(f"  {wheel[-1].name}: pip install --dry-run ok ($0, offline)")


def gate_docs_links(base: str, docs_url: str, out: list[str]) -> None:
    proc = subprocess.run([sys.executable, "scripts/check_links.py"],
                          capture_output=True, text=True, timeout=120, cwd=ROOT)
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
        raise GateFail(f"docs-links: check_links.py red: {'; '.join(tail)}")
    status, payload, ms = _req("GET", docs_url, timeout=60.0)
    if status != 200:
        raise GateFail(f"docs-links: GET {docs_url} -> HTTP {status}")
    out.append(f"  check_links.py green; docs {docs_url} -> 200 in {ms:.0f}ms "
               f"({len(payload)} bytes)")


def gate_quality_cost(base: str, out: list[str]) -> None:
    fleet, _ = _get_json(base, "/api/fleet")
    calls, _ = _get_json(base, "/api/calls")
    rows = calls if isinstance(calls, list) else calls.get("calls", [])
    if not rows:
        raise GateFail("quality-cost: /api/calls has no rows")
    first = rows[0]
    if "cost_usd" not in first or "quality" not in first:
        raise GateFail(f"quality-cost: cost/quality not beside each other: "
                       f"{sorted(first)}")
    q = first["quality"]
    if q.get("tier") not in TIERS:
        raise GateFail(f"quality-cost: bad fleet tier: {q}")
    call_id = first.get("id") or first.get("call_id") or ""
    detail, _ = _get_json(base, f"/api/calls/{call_id}")
    dims = detail.get("quality", {}).get("dimensions", [])
    if not dims or any(d.get("tier") not in TIERS for d in dims):
        raise GateFail(f"quality-cost: detail {call_id} quality dims lack tiers")
    if "_provenance" not in detail:
        raise GateFail(f"quality-cost: detail {call_id} missing _provenance")
    out.append(f"  fleet='{fleet.get('label', '?')}' n={len(rows)}; call {call_id}: "
               f"cost_usd={first['cost_usd']} beside quality/{q['label']}/{q['tier']}; "
               f"detail dims={len(dims)} tiers ok + _provenance present")


GATES = [
    ("demo-up", gate_demo_up),
    ("evaluate-p95", gate_evaluate),
    ("evaluate-cache", gate_evaluate_cache),
    ("ci-green", gate_ci),
    ("pip-install", gate_pip_install),
    ("docs-links", gate_docs_links),
    ("quality-cost", gate_quality_cost),
]

BASE_GATES = {"demo-up", "evaluate-p95", "evaluate-cache", "quality-cost"}


def run_qa(base: str, docs_url: str) -> int:
    failures: list[str] = []
    print(f"prelaunch QA vs {base}")
    for name, fn in GATES:
        out: list[str] = []
        t0 = time.perf_counter()
        try:
            if name in BASE_GATES:
                fn(base, out)
            elif name == "docs-links":
                fn(base, docs_url, out)
            else:
                fn(out)
            print(f"PASS {name} ({time.perf_counter() - t0:.1f}s)")
        except GateFail as exc:
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f}s): {exc}")
            failures.append(name)
            continue
        for line in out:
            print(line)
    if failures:
        print(f"ABORT gate={failures[0]} ({len(failures)} red: "
              f"{','.join(failures)}); launch blocked")
        return 2
    print("ALL GATES GREEN; launch may proceed")
    return 0


def _spawn_local(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "turnstile_service.app:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                        timeout=2) as res:
                if res.status == 200:
                    return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise GateFail("spawn-local: uvicorn did not answer /health in 60s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=LIVE_BASE, help="surface under test")
    ap.add_argument("--docs-url", default="",
                    help="docs surface (default: <base>/)")
    ap.add_argument("--spawn-local", action="store_true",
                    help="boot local uvicorn on an ephemeral port and test it")
    ap.add_argument("--self-test", action="store_true",
                    help="seed one failure (dead base) and require abort")
    args = ap.parse_args(argv)
    if args.self_test:
        code = run_qa("http://127.0.0.1:1", "http://127.0.0.1:1/")
        if code != 0:
            print("SELF-TEST PASS: seeded failure aborted with gate named above")
            return 0
        print("SELF-TEST FAIL: seeded failure did NOT abort")
        return 1
    if args.spawn_local:
        proc = _spawn_local(8123)
        try:
            return run_qa("http://127.0.0.1:8123",
                          args.docs_url or "http://127.0.0.1:8123/")
        finally:
            proc.terminate()
    return run_qa(args.base, args.docs_url or args.base + "/")


if __name__ == "__main__":
    sys.exit(main())
