# Day 3 PRD — Make the logic faster (measured)

**Inherits `00-charter.md` in full.** Executor: OpenCode · Reviewer: Claude · Depends on:
Day-1 (service), Day-2 (data) · Feeds: Day-5 (monitoring), Day-6/7 (the perf story).

## Objective
Turn "feels fast" into **benchmarked, behavior-preserving speedups** with observability —
so "as responsive as real-time" is a measured claim, not a hope.

## Connection (charter §5)
Speeds the Day-1 service and Day-2 ingest; the cache/job **observability** it adds is what
Day-5 monitors; the before/after numbers become the Day-6 `PERF.md` and Day-7 launch story.
It MUST NOT change any `/api/*` shape or report bytes (charter §4, §1.6).

## Day-specific strict rules (add to charter §1)
- Every optimization MUST be **behavior-preserving**: outputs byte-identical, determinism
  intact, accuracy unchanged. A change that moves any output byte MUST be reverted.
- Every speedup claim MUST be a **measured before/after with stated methodology** (n,
  hardware, seed) — no unquantified "faster." (Honesty discipline, charter §1.4.)
- Parallelism MUST NOT introduce nondeterminism; parallel aggregates MUST equal serial
  byte-for-byte.

## Priority factors
### P0 — base case (MUST)
1. A **benchmark harness** (pytest-benchmark or a seeded timed script) over
   price→verdict→detect→replay and the experiment matrix; **baseline recorded**.
2. Profile (cProfile/py-spy) and optimize the **top 2–3 hot paths**, behavior-preserving.
3. **Parallelize the experiment matrix** (pool over independent traces) in the experiments
   layer + the service job runner; byte-identical aggregates.
4. **Cache/job observability**: hit-rate + timing counters exposed (in-memory), readable
   via an endpoint or the job result.
5. `PERF.md` with before/after tables + methodology.

### P1 — build-on-top (SHOULD)
6. Async I/O + response compression on the service. 7. Warm/precompute the committed
   fleet cache at boot. 8. Memoize pricing by content hash within a request.

### P2 — stretch (MAY)
9. numba/Cython on the pricing hot loop **only if** profiling shows it dominates, behind a
   pure-Python fallback (no new hard dep).

## Latency budget (charter §2 — these are the day's gates, set the exact numbers from the
recorded baseline first, then hold them)
- Experiment matrix over 250 traces MUST be **≥ 2× faster** than the serial baseline.
- Cache-hit eval **p95 < 50 ms**; single-call cold eval **p95 < 300 ms**.
- Per-trace price+verdict+detect MUST NOT regress vs baseline (report the measured µs).

## Interfaces
No API-shape change. Add: a benchmark entry point (`packages/experiments/bench.py` or
similar), an observability read (extend `/api/status` or the job result with hit-rate +
timings), `PERF.md`. Parallelism via stdlib (`concurrent.futures`), no external queue.

## Acceptance criteria (EARS)
- WHEN the same call is evaluated twice, the second SHALL return **byte-identical** bytes
  from cache in **< 50 ms**. *(check: timed double-POST + byte-diff)*
- WHEN the experiment matrix runs parallel on K cores, it SHALL complete **≥ 2×** faster
  than serial **and** produce byte-identical aggregates. *(check: benchmark + diff gate)*
- IF an optimization changes any output byte, THEN it SHALL be reverted. *(check: a
  golden-output diff gate in the loop)*
- WHILE observability is on, the service SHALL expose cache hit-rate + median/p95 timings.
  *(check: read the endpoint after a mixed load)*

## Recursive loop — Day-3 dynamic checks (charter §3)
For each optimization: run the benchmark **before and after**, run the **byte-identical
output diff gate** over the golden + ingest outputs, and confirm the target speedup +
budget. If bytes moved → the optimization is a defect → revert/fix → re-loop. Drive the
running service for the cache-hit and observability checks. Attach benchmark + diff
transcripts. Never accept a speedup that a dynamic check shows changed an output.

## Risks & mitigations
- "Optimization" that changes numbers → the byte-diff gate catches it every loop.
- Parallel nondeterminism → aggregate-equality gate; fixed seeds; ordered reduce.
- Micro-optimizing cold paths → profile first, optimize only what dominates.

## Out of scope
Real paid variant sweep (not $0). A rewrite in another language.

## Reviewer gate (Claude)
Speedups are measured + behavior-preserving (byte-diff green); matrix ≥2× with identical
aggregates; observability live; PERF.md methodology sound; `/api/*` bytes unchanged; CI green.
