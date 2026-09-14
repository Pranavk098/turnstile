# PRD 03 — Fast & stable eval engine (caching + async experiment API)

**Owner (spec):** Pranav Koduru · **Executor:** OpenCode · **Reviewer:** Claude
**Status:** ready to build · **Roadmap:** the "fast + stable" pillar (extends the
already-shipped demo API from PRD 01)

---

## 1. Thesis

The offline engine is already deterministic and fast for a single call. Two things
are missing before "the whole system is quick at running evals" is true:

1. **Repeat work is recomputed.** Every eval re-prices/re-adjudicates/re-detects from
   scratch, even for an identical call under an identical rate table.
2. **The experiment/replay matrix has no service surface.** The credibility engine —
   variant sweeps over many calls with §8.3 gating — is CLI-only. A visitor or a
   front-end cannot run "sweep this fleet on the cheaper router" and get a gated
   result back without blocking on a long synchronous request.

This PRD adds a **content-hash cache** and a **bounded, in-process async job API** for
experiment/replay, so eval runs are fast on repeat and non-blocking at volume — while
staying $0, deterministic, and stateless-friendly on a free host.

## 2. Non-goals

- **No paid path.** MockBackend / deterministic re-pricing only; no live model call.
- **No external infra.** No Redis, Celery, DB, or paid queue — in-process asyncio +
  an in-memory job store only (must run in the single free-tier container from PRD 01).
- **No new eval math.** Caching and job orchestration wrap the existing engine; results
  must be byte-identical to the uncached/synchronous path.
- **No persistence of user data.** Jobs and their inputs live in memory, bounded, and
  are evicted; nothing is written to disk for uploaded calls.

## 3. Hard constraints

1. **$0**, free-tier, no paid call anywhere.
2. **Determinism preserved.** Cache hits and async results must equal the direct
   engine output exactly (same bytes). Any nondeterminism is a bug.
3. **Engine purity.** No business math added; cache/jobs call the existing entry
   points (`price_trace`, `adjudicate`, `detect`, `replay`/`experiment`, `run_calls`,
   `aggregate_experiment`).
4. **Bounded.** Cache size-capped with eviction; jobs count- and input-capped
   (reuse PRD 01's `MAX_CALLS`-style limits); a rejected job never runs the engine.
5. **Frozen contracts untouched.**

## 4. Architecture

### 4.1 Content-hash cache (fast repeat)

- A pure function `eval_key(call_json, rates_sha, baselines_sha) -> str` (sha-256 over
  the normalized call + the rate/baseline identities the manifest already records).
- Cache `call_json → per-call report` (the `run_call` output) in a bounded LRU
  (stdlib `functools.lru_cache` won't work on dicts — use an explicit small
  `OrderedDict`-based LRU keyed by `eval_key`, size-capped, thread-safe).
- Wire it *inside the service layer*, not inside the engine (keep the engine pure): the
  service checks the cache before calling `run_calls`, and stores the result after.
- **Invalidation is automatic**: the key includes the rate-table and baselines SHA, so
  a rate change is a different key — never a stale hit.

### 4.2 Async experiment/replay job API (non-blocking at volume)

New endpoints (in `packages/service`):

```
POST /api/experiments        body: {calls:[...], variant: VariantSpec}  -> {job_id, status:"queued"}
GET  /api/experiments/{id}   -> {status: queued|running|done|error, result?: ExperimentResult, error?}
```

- An in-process job runner: `asyncio` task + an in-memory `dict[job_id, JobState]`,
  bounded (max N concurrent, max M queued; past caps → 429). No external worker.
- The job calls the **existing** experiment/replay path (MockBackend variant sweep with
  `aggregate_experiment` + §8.3 gating) — no new statistics.
- Results carry the same provenance/tier labels and the same `ExperimentResult` shape
  the CLI produces. Bounded input (same call cap as `/api/evaluate`).
- Job state is ephemeral: evicted after a TTL or when the store is full; the API says so
  (404 on an evicted/unknown id).

## 5. Build phases

- **P0 — `eval_key` + LRU cache module** (pure, unit-tested). *Verify:* identical
  input → same key; a rates-SHA change → different key; LRU evicts at cap.
- **P1 — Service cache wiring on `/api/evaluate`.** *Verify:* a cache-hit response is
  byte-identical to the cold response and skips the engine (assert via a spy/counter);
  parity with the CLI still holds.
- **P2 — Job runner + `/api/experiments` endpoints.** *Verify:* submit → poll → done;
  result equals the CLI experiment over the same calls+variant; over-cap submit → 429;
  unknown/evicted id → 404; determinism across two identical jobs.
- **P3 — Concurrency/stability.** *Verify:* a test fires K concurrent evaluates +
  experiments; no shared-mutable-state corruption, no cross-request bleed, all results
  correct; the shared engine (`_engine()` rates/baselines) stays read-only.

## 6. Definition of Done (prod-ready)

- [ ] Repeat eval of an identical call is served from cache, byte-identical, without a
      second engine run (proven by a call-counter test).
- [ ] Cache is bounded + auto-invalidated by rate/baseline SHA (no stale hits).
- [ ] `POST /api/experiments` runs the gated variant sweep asynchronously; `GET`
      returns the same `ExperimentResult` the CLI produces, with provenance/§8.3 labels.
- [ ] Jobs are bounded (429 past caps), ephemeral (404 after eviction), and never run
      the engine on a rejected submission.
- [ ] Concurrent load is correct and deterministic; engine stays pure and read-only.
- [ ] `$0`/no-paid-path proven; runs in the single PRD-01 container (no new infra).
- [ ] `uv run pytest` green incl. new tests; full suite not regressed.

## 7. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| Cache returns a stale result after a rate change | High | Key includes rates+baselines SHA; test the invalidation |
| In-memory job store leaks memory | Med | Hard caps + TTL eviction; a test asserting eviction |
| Async introduces nondeterminism | Med | Results compared byte-for-byte to the sync/CLI path in tests |
| Concurrency corrupts shared state | Med | Engine loaded read-only once; no mutable module state; concurrency test |

## 8. Out of scope / future

- Persistent job history, result storage, or a real queue (only if the tool leaves
  demo scope).
- Paid live-model replay (still roadmap "paid preservation", separate).

## 9. Handoff / dependencies

- Builds on PRD 01's service. Independent of PRD 04, but PRD 05's "compare runs" UI
  consumes `/api/experiments`, so land 03 before 05.
- **Reviewer will check:** byte-identical cache/async results vs. the engine, bounded
  eviction, $0/no-infra, concurrency correctness, engine purity.
