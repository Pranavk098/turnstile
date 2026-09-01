# Performance & Parallelization Audit — Turnstile

**Author:** GLM 5.3 (OpenCode), read-only analysis + local benchmarks, 2026-08-31
**Branch audited:** `wave0-foundation` @ `bb7d0f4` (+ uncommitted in-progress `checkpoint_runner.py` diff noted)
**Purpose:** Change B (concurrency) is the ledger's declared next step. This audit establishes, with measurements, *where* the wall-clock actually goes, *what* is safely parallelizable, and *what must be fixed before concurrency buys anything*. Companion docs: `07-full-codebase-audit.md` (correctness findings, several of which gate the paid run), `08-progress-and-gtm-gap.md` (progress/GTM distance).

---

## 1. Executive summary

1. **The entire local pipeline is ~0.2 s at corpus scale (measured).** Generation, pricing, adjudication, all 10 detectors, baselines, and a full MockBackend matrix over n=250 are noise. **100% of the 4–8 h projected wall-clock is OpenAI API latency.** No CPU parallelization anywhere else in the repo is worth anything.
2. **The API call map is embarrassingly parallel — verified in code, not asserted.** `replay()` builds each backend call's context from the **original** trace (`replay.py:118`: `turns_before` = original turns, never regenerated), so every `(variant, trace, llm-span)` backend call is independent of every other. The sequential `for` at `replay.py:112–120` is a map over a flat set, followed by a cheap (<10 ms/trace) local reduce.
3. **But concurrency is not the binding constraint on validity — three correctness findings are** (`07-full-codebase-audit.md` CR-A/CR-B/H-1): the replay prompt omits the caller utterance the decision responds to (30/30 turn-0 prompts have zero conversational content); the Δcost metric carries a measured ~4.4× token-scale artifact that biases *every* variant toward "savings"; and outcome-preservation is structurally pinned near 1.0 because verdict labels are driven by pinned tool effects. **Fix these first or the parallel run produces a precise, fast, wrong headline.**
4. Correctly sized, the routing-only n=250 run goes from **~4–8 h sequential to ~30–60 min at k=8 workers**, bounded by your account tier's RPM/TPM — which smoke #3 must measure before k is committed.

---

## 2. Measured baseline (this machine, seed 0, MockBackend, zero spend)

| Stage | Scale | Wall time |
|---|---:|---:|
| `generate_corpus` | n=30 / n=250 | 0.02 s / 0.08 s |
| `price_trace` over corpus | n=250 | <0.01 s |
| `compute_baselines` | n=250 | 0.01 s |
| `adjudicate` + `detect` sweep (3,256 findings) | n=250 | 0.02 s |
| `run_matrix` (1 variant, MockBackend) | n=30 | 0.07 s |
| `bootstrap_ci` (250 values, 10k resamples) | — | 0.07 s |

Call volume for the paid run (from `estimate_cost`, the production path): **routing-only n=250 ≈ 1,733–2,300 decisions** (my n=5 free run measured 46 calls/5 traces; the ledger's n=250 corpus computation says 1,733 — use `estimate_cost`, it's exact). Observed real-backend latency from smokes #1/#2: **~5–12 s/call** (gpt-5 family, reasoning, no `max_tokens` cap — see §5.3).

**Sequential projection:** 1,733–2,300 calls × 5–12 s ≈ **2.5–7.7 h**. The full 6-variant matrix (pre-guard) would have been ~10,723 calls ≈ 15–36 h — the variant-scope restriction already removed ~5/6 of that.

## 3. Where the sequential loop actually lives

| Location | Shape | Parallel? |
|---|---|---|
| `replay.py:112–120` — `for turn_idx, span in targets: backend(...)` | one blocking API call per llm span ≥ from_turn | **Yes** — each call's `ReplayContext` is built from the ORIGINAL trace (`:118`); results land in a `span_id`-keyed dict |
| `replay.py:191` — `experiment()` list comp over traces | one `replay()` per trace | **Yes** — traces are independent |
| `checkpoint_runner.py:83–89` — per-trace loop + store put | checkpointed map | **Yes**, with a store lock (§6.2) |
| `stats.bootstrap_ci:70–71` — 10k `rng.choice` loop | CPU | Vectorizable (one-liner), but 0.07 s — **not worth touching now** |
| Everything else (corpus, pricing, verdict, detectors, sweeps) | local | No need — total ≈ 0.2 s |

**Why the map is safe:** pinned replay (PRD §8.1) fixes the caller side; the backend never sees another call's output; `replaced[span.span_id]` is a pure scatter. The only intra-trace dependency is in the *reduce* (rebuild → price → adjudicate), which is pure CPU. `OpenAIBackend.__call__`'s only cross-call state is the progress counter (`openai_backend.py:107`) — a benign race, but guard it anyway (§6.2).

**The contract constraint that shapes the design:** `replay()`'s signature is **frozen by PRD §5** (no added parameters). So concurrency cannot be an `executor=` arg on `replay()`. Two clean options:

- **Option 1 (recommended): split-and-compose, additively, in `packages/replay`.** Extract the map and reduce into two new public functions — `collect_decisions(trace, variant, from_turn, backend) -> dict[span_id, ReplayedDecision]` (the parallelizable part) and `finish_replay(trace, variant, from_turn, replaced) -> Trial` (the local part) — and re-express `replay()` as their composition. Signature unchanged, zero drift (one implementation), and `packages/experiments` gains `run_experiment_concurrent` that maps with a `ThreadPoolExecutor` and reduces with the shared `finish_replay`. This is the checkpoint_runner pattern extended: the runner mirrors `experiment()`, not `replay()`'s internals.
- **Option 2: concurrent runner fully inside `packages/experiments`** duplicating the rebuild logic. Rejected — duplicates `replay()`'s rebuild/adjudication rules; drift risk on the exact code the headline depends on.

## 4. Wall-clock math (routing-only, n=250)

| k workers | Calls ≈ 2,000 | @ 9 s/call | Bound |
|---:|---:|---:|---|
| 1 | 2,000 | ~5.0 h | — |
| 4 | 2,000 | ~1.25 h | likely under RPM caps |
| 8 | 2,000 | ~37 min | **recommended first target** |
| 16 | 2,000 | ~19 min | only if smoke #3 shows headroom |

The binding constraint is the account tier's **RPM/TPM** for `gpt-5`/`gpt-5-mini`/`gpt-5-nano` — which we have never measured (no completed paid run). **Protocol:** smoke #3 (n=30, routing-only, k=8) reports achieved calls/min and 429 rate; set k for n=250 to ~70% of the measured RPM ceiling. The SDK's `max_retries=5` with backoff (landed in the resilience fix) already absorbs transient 429s; sustained 429s mean k is too high.

Worst-case tail: one stalled call = 60 s timeout × 5 retries ≈ 5 min (bounded, checkpointed — smoke #1's unbounded 38-min hang is structurally fixed).

## 5. Latency levers besides concurrency (owner decisions, in impact order)

1. **Pin unrouted decision kinds (BIGGEST — changes semantics, needs owner + PRD note).** Under `model_routing={"route": "gpt-5-nano"}`, only `route` decisions are variant-affected — yet `_earliest_applicable_turn` returns turn 0 and `replay()` re-runs **every** llm span, with `OpenAIBackend` falling back to the original model for non-routed kinds (`openai_backend.py:96–98`). That is ~9 calls/trace where ~1 is variant-informative. Pinning non-routed kinds to their original spans (MockBackend's own identity semantics, `backend.py:160–161`): calls drop **~9× → ~250** (≈ 40 min sequential, ≈ 5 min at k=8; cost → ~$0.05), and Δcost attribution becomes causal ("only where the variant acts") instead of mixing in same-model sampling noise. **Cost:** deviates from PRD §8.1's "all llm.decide spans from from_turn are re-run" — one sentence needs an owner-approved errata. This is the difference between a 4–8 h run and a <1 h run; decide it before smoke #3.
2. **`max_tokens` cap on completions.** None is set (`openai_backend.py:102–104`); a reasoning model can emit long completions, inflating both latency and cost. Corpus output tokens are ≤ ~200; cap at a generous bound (e.g. 256) and count violations.
3. **OpenAI Batch API** — 50% cost, 24 h turnaround. Irrelevant at $0.41 unless rate limits are brutal. Noted for completeness, not recommended.

## 6. Prerequisites Change B must satisfy (concurrency-specific)

1. **Thread-safe checkpoint.** `CheckpointStore.put` (`checkpoint_runner.py:61–67`) opens/appends/fsyncs per trial with no lock. Under a pool, appends can interleave. Fix: a `threading.Lock` around put (and make `_done` reads safe), or per-worker buffers flushed under a lock. Keys are unique per worker task, so no dedup logic is needed.
2. **Guard the progress counter** (`openai_backend.py:107–114`) with the same lock discipline (benign today, wrong in review).
3. **Shared client.** One `OpenAI` client across workers (httpx pool) — do NOT construct per call. Keep `timeout`/`max_retries` as landed.
4. **Resume under concurrency:** partition `(variant, trace)` tasks by key *after* loading the store; completed keys skip silently. `store.get` before submit, exactly as the sequential loop does.
5. **Fail-before-spend writability check** (currently the final `results.json` write happens *after* the whole run, `run_experiments.py:117`; the n=2 probe lost its result to exactly this class of error): touch/validate `--out` and the checkpoint path *before* any backend call.
6. **Determinism:** corpus regeneration from `(n, seed)` is already exact (`generate.py:493–501`), so resume keys match. Real-backend trials are inherently nondeterministic (sampling) — that is fine; the manifest + seed pin everything else.

## 7. What NOT to parallelize

Everything except the backend-call map. The detectors/pricing/verdict stack runs in 0.02 s over 250 traces; sweeps are single-threaded CLIs with a monkeypatched module global (`sweeps.py:150–160`) that is **explicitly not thread-safe** and must stay single-threaded (documented in the ledger). Vectorizing `bootstrap_ci` is optional polish, not a need. Process pools are pointless — the workload is I/O-bound; threads are correct.
