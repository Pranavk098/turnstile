# PERF.md — Day-3 speed: benchmarked, behavior-preserving speedups

## Objective

Turn "feels fast" into **benchmarked, behavior-preserving speedups** with
observability (Day-3 PRD, inherits charter `docs/prd/sprint-01/00-charter.md`
in full). Every optimization below kept outputs byte-identical; every speedup
claim carries its methodology (n, hardware, seed). No `/api/*` shape change,
no `packages/schema` change, no pricing-formula change — additive
observability fields only.

## Methodology

- **Harness:** `packages/experiments/bench.py` (committed, Track A) —
  `per-trace` times price→verdict→detect per trace (median/p95 µs);
  `matrix` times the serial MockBackend experiment matrix (wall seconds).
  Parallel numbers come from `run_matrix_checkpointed_detailed(..., max_workers=8)`
  over fresh temp checkpoints (a reused checkpoint would serve cached trials
  and misreport a resumed wall as a full-run wall).
- **n / seed:** per-trace n=50, seed=0, repeat=5 (250 samples);
  matrix n=250, seed=0, repeat=3 (serial) / repeat=3 (parallel, workers=8).
- **Hardware:** Windows-11-10.0.26200-SP0, 20 CPUs, python 3.13.12.
- **Backend / spend:** `MockBackend` only, $0 (`bench.py` refuses `--paid`
  and `TURNSTILE_ALLOW_PAID=1` by design).
- **Commits:** baseline `e01205c` (Track A, `experiments/baseline-day3*.json`);
  after-runs on the working tree over `1f3bc18` (Day-3 Tracks B–D).
- **Service checks:** real uvicorn over loopback (`POST /api/evaluate` with the
  `docs/INGEST.md` doc-example call; `GET /api/status`), client-side wall ms.

## Before–After tables

### Per-trace price→verdict→detect (µs; n=50, seed=0, repeat=5, Win11/20-CPU, py3.13.12, MockBackend)

| | median | p95 | mean |
|---|---|---|---|
| Before (`experiments/baseline-day3-pertrace.json` @ `e01205c`) | 123.0 | 1253.0 | 398.8 |
| After (`bench.py --mode per-trace`, tree over `1f3bc18`) | 76.3 | 155.9 | 91.0 |

No regression vs baseline; p95 fell ~8× (1253.0 → 155.9 µs,
n=50/seed=0/Win11-20CPU/py3.13.12) because the old p95 was dominated by
repeated optional-dependency probing on the detect path (see Hot paths).

Finer split, same n/seed/hardware (Track B bench, adjudicate+detect plus
price-only):

| | pipeline median | pipeline p95 | price-only median |
|---|---|---|---|
| Before | 130.8 | 1377.2 | 19.8 |
| After | 85.3 | 155.5 | 10.0 |

### Experiment matrix wall seconds (n=250, seed=0, Win11/20-CPU, py3.13.12, MockBackend)

| | per-repeat walls | median |
|---|---|---|
| Serial before (baseline `experiments/baseline-day3.json` @ `e01205c`, repeat=5) | 1.070 / 0.788 / 1.150 / 1.173 / 1.072 | 1.072 |
| Serial after (`bench.py --mode matrix`, repeat=3) | 0.793 / 0.809 / 0.855 | 0.809 |
| Parallel after (`max_workers=8`, repeat=3) | 0.182 / 0.216 / 0.176 | 0.182 |

**Speedup (serial-median ÷ parallel-median) = 4.46×
(n=250, seed=0, Win11/20-CPU, workers=8, MockBackend)** — gate is ≥2×: GREEN.
Aggregates byte-identical (sha256 `8d5f7ce7…` both sides; variant
`model_routing_gpt5_nano` delta_cost_mean −0.000126, n=231, both paths).

### Cache-hit eval (running service; INGEST.md doc call; 8291-byte response)

| | wall ms | bytes |
|---|---|---|
| First POST (miss, cold key) | 89.4 | 8291 |
| Second POST (hit, same body) | 1.4 | 8291, byte-identical |

Gate: second identical POST byte-identical **and < 50 ms** — GREEN (1.4 ms).
In-suite proof: `packages/service/tests/test_observability.py::test_double_post_byte_identical_and_fast`.

### Cold single-call eval (running service; 6 distinct ids = 6 fresh keys)

min 62.3 / p50 62.9 / p95 66.1 / max 66.1 ms (n=6, same service/hardware).
Gate: single-call cold eval p95 < 300 ms — GREEN (max observed 66.1 ms).

## Hot paths optimized

Profiled with cProfile over 5 reps × (50 adjudicate+detect + 50 MockBackend
replays), n=50/seed=0 (excerpt, ordered by internal time):

```text
ncalls  tottime  filename:lineno(function)
  7545    0.007  pydantic_core validate_python
   250    0.007  replay.py:194 replay_with_real_usage_cost
  3870    0.005  pydantic main.py:971 __copy__
   250    0.003  pricing.py:86 price_trace
   250    0.002  d08_silence_tax.py:102 detect_...
  9050    0.002  pricing.py:64 _cost_llm
   250    0.001  d03_redundant_retrieval.py:142 detect_redundant_retrieval
   250    0.001  detect.py:38 detect
```

What the profile showed, and the behavior-preserving fix for each:

1. **Pricing loop attribute/global lookups** (`pricing.py:price_trace`) —
   hoisted the rate-table dicts and key/cost helpers to locals once per
   trace. Loop order, key construction, and float operation order untouched;
   the four `_cost_*` formulas are verbatim (PRD §4.2 "do not alter").
2. **Replay per-span scans** (`replay.py:replay_with_real_usage_cost`) —
   the old loop did a linear `next(...)` turn scan plus a full
   `tuple(t for t in turns if ...)` filter per replaced span
   (O(spans × turns)); hoisted to `turns_by_index` + a per-turn
   `turns_before` cache holding the exact same objects in the exact same
   order. Price-only median 19.8 → 10.0 µs (n=50/seed=0/same hardware).
3. **Detector embedder re-probing** (`d03_redundant_retrieval.py`) —
   `lru_cache` only caches a *successful* model load, so with the optional
   `embed` extra absent every retrieval span re-attempted the import+load
   (~50% of the detect hot loop). Added an `_EMBEDDER_INERT` negative cache:
   once the cosine half proves inert it stays inert for the process.
   Returns `None` in exactly the same cases — outputs unchanged.
4. **Checkpoint fsync frequency** (`checkpoint_runner.py`) — sequential path
   keeps per-trial put+fsync (a crash loses nothing); the parallel path
   group-commits one worker chunk per fsync (`put_batch`, same record bytes
   via the shared `_stage_locked` path). Variants stay sequential.

P2 (numba) **skipped with numbers**: the profile shows the pricing loop is
*not* dominant (`price_trace` tottime 0.003 s of 0.081 s; the top rows are
pydantic validation/copy and replay orchestration), so per the PRD a numba
hot-loop rewrite is out of scope.

## Parallelism correctness (ordered reduce + hash equality)

- `checkpoint_runner`: pending traces split into ≤ `max_workers` **contiguous**
  corpus chunks (one task per worker); `executor.map` yields chunk results in
  corpus order; each chunk group-commits in corpus order. Resume semantics
  unchanged (completed keys skip exactly as the sequential loop does).
- `jobs._map_trials_ordered`: per-trace `map_trials([pt], variant)` shards on
  a `ThreadPoolExecutor`; futures map to corpus indices and assemble back in
  input order regardless of completion order; one `aggregate_experiment`
  reduce — byte-identical to sequential by construction.
- Proof: serial-vs-parallel n=250 hashes equal (`8d5f7ce7…`); unit gates with
  jitter backends that scramble completion order —
  `test_concurrent_matrix_is_byte_identical_to_sequential`,
  `test_parallel_workers4_matches_serial_with_jitter_backend`,
  `test_run_experiment_job_parallel_matches_sequential` (all green in
  `uv run pytest`).

## Observability (status fields + how to read)

`GET /api/status` (lightweight: no engine run, no body read; `Cache-Control:
no-store`) keeps every Day-1 field (`ok`, `commit`, `uptime_sec`, `warm`,
`engine_loaded`) and adds:

```json
{"cache": {"entries": 7, "byte_size": 57509, "hits": 1, "misses": 7,
           "hit_rate": 0.125},
 "timings_ms": {"evaluate_median": 60.96, "evaluate_p95": 99.23}}
```

How to read: `hit_rate` = hits ÷ (hits + misses) over process life;
`timings_ms.evaluate_*` = full-handler wall ms of `/api/evaluate` (body read
+ parse + key + cache-or-engine + serialize) over the last ≤512 samples —
the whole serve cost, not the cache-lookup slice. With no evaluate traffic
yet it falls back to cache-lookup timings; with no data at all both read
`0.0`. Experiment jobs carry their own envelope at
`GET /api/experiments/{id}`: `timings: {queue_ms, run_ms}` + `workers`
(result payload itself stays width-invariant so the parallel==serial gate
holds over the whole dict). Live sample after an 8-request mixed load
(1 hit + 7 misses): `hit_rate 0.125`, `entries 7`, `evaluate_median 60.96`,
`evaluate_p95 99.23`.

P1 notes: GZip + cache-policy middleware were already present
(`GZipMiddleware(minimum_size=1024)`; `no-store` on POST/status, short public
cache on reads) — verified as-is, not added twice. Within-request pricing
redundancy is already eliminated by the hoisted invariants above (Track B) —
referenced here, not duplicated. Committed fleet bytes are preloaded once at
app boot (read-only snapshot; status path never touches the engine).

## Honesty note

Tier vocabulary, verbatim — **measured / instrumented / not-measured**:

- **measured:** all wall timings (bench.py per-trace/matrix, service
  double-POST + cold-eval client walls), cache counters + `hit_rate`, the
  4.46× matrix speedup, and every byte-identity claim (sha256 / byte-diff).
- **instrumented:** the cProfile tottime ranking above (deterministic
  instrumentation, not wall truth — used only to *choose* hot paths, never
  as a speedup claim) and the `/api/status` median/p95 over bounded recent
  samples (a windowed instrument, not a full-distribution statistic).
- **not-measured:** anything requiring a calibrated judge or paid backend —
  none claimed here; the matrix runs `MockBackend` (mechanism, not a measured
  production rate) and says so in its provenance.

No bare comparative claim appears without n/hardware/seed; no uncalibrated
score reaches any headline.

## Repro commands

```bash
# Benchmarks ($0, MockBackend only)
uv run python packages/experiments/bench.py --n 50 --seed 0 --mode per-trace
uv run python packages/experiments/bench.py --n 250 --seed 0 --mode matrix --out experiments/baseline-day3.json

# Full suite (must stay green) + Day-3 gate tests
uv run pytest
uv run pytest packages/service/tests/test_observability.py \
  packages/service/tests/test_jobs.py \
  packages/experiments/tests/test_checkpoint_runner.py -q

# Cache-hit gate against a running service (second POST: identical bytes, <50ms)
uv run uvicorn turnstile_service.app:app --port 8000 &
curl -s -X POST localhost:8000/api/evaluate -H 'Content-Type: application/json' \
  -d @packages/service/src/turnstile_service/example_call.json -o /tmp/hit1.json -w '%{time_total}\n'
curl -s -X POST localhost:8000/api/evaluate -H 'Content-Type: application/json' \
  -d @packages/service/src/turnstile_service/example_call.json -o /tmp/hit2.json -w '%{time_total}\n'
cmp /tmp/hit1.json /tmp/hit2.json && curl -s localhost:8000/api/status
```
