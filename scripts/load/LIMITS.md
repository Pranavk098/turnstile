# Load limits — POST /api/evaluate (Day-5 Part E, P1 #6)

## Sustained number (measured, this hardware only)

**9.6 RPS sustained at p95 249 ms over a 60.2 s run (n=577, errors=0) —
GREEN against the p95 < 300 ms budget.** Miss path (unique ids, full engine
run per request), 2 concurrent workers, single-worker uvicorn.

## Full 60-second transcript (seed=0)

Machine: Windows-11-10.0.26200-SP0, 20 CPUs, python 3.13.12.
Server: real uvicorn subprocess (`turnstile_service.app:app`), fresh boot per
run; demo rate limiter raised via env for the harness only (shipped defaults
untouched). Warm: 5 doc-example POSTs, median 15.2 ms, all 200.

| run | path | n | workers | wall_s | rps | median_ms | p95_ms | max_ms | errors |
|---|---|---|---|---|---|---|---|---|---|
| fixed probe | miss | 200 | 8 | 19.8 | 10.1 | 832.9 | 916.1 | 1013.3 | 0 |
| fixed probe | hit | 200 | 8 | 0.4 | 533.3 | 6.8 | 31.8 | 125.6 | 0 |
| 60 s (w1) | miss-sustained | 512 | 1 | 60.1 | 8.5 | 116.4 | 152.3 | 166.1 | 0 |
| **60 s (w2) ← claim** | **miss-sustained** | **577** | **2** | **60.2** | **9.6** | **201.0** | **249.2** | **283.9** | **0** |
| 60 s (w3) | miss-sustained | 660 | 3 | 60.2 | 11.0 | 281.4 | 381.5 | 438.6 | 0 — OVER BUDGET |

Target derivation: PERF.md cold single-call eval p95 = 66.1 ms (n=6) +
cache-hit 1.4 ms [both measured] + a live warm median taken at runtime
(15–17 ms across runs); budget p95 < 300 ms. Bracketing: w3 reaches 11.0 RPS
but p95 381 ms breaks the budget; w1 holds p95 152 ms at only 8.5 RPS. w2 is
the highest RPS whose measured p95 stays < 300 ms.

Notes (measured, not gated): the single-loop uvicorn serializes the sync
engine run, so added concurrency buys queueing latency, not throughput —
miss latency scales ~linearly with workers (fixed probe: 833 ms median at 8
workers). Per-request cost also drifts up over a long run on a fresh boot
(w2: 125 ms fixed-phase median → 201 ms sustained median) as the in-memory
EvalCache grows; a production reading needs a warmed, steady-state server.
Hit path (repeated doc-example body) is cache-bound: 533 RPS at p95 32 ms.

## Repro

```bash
uv run python scripts/load/load_test.py --target
uv run python scripts/load/load_test.py --smoke      # the ONLY mode CI may run
uv run python scripts/load/load_test.py --workers 2 --requests 10 --duration 60
```

## Caveat

**Re-run on release hardware before quoting this number anywhere else.**
It is machine-relative (this dev box, this Python, loopback) and DOCUMENTED,
never CI-gated: no timing constant lives in code or CI (charter: machine-
relative gates flake).
