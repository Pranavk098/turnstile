# GLM brief — paid-run hardening (replay + experiments correctness + concurrency)

**From:** Claude/owner lane · **For:** GLM 5.3 (OpenCode), in your clone `C:\Users\prana\turnstile-oc`
**Base:** `wave0-foundation` @ `bb7d0f4` (fetch it; this brief commit sits on top).
**Branches:** one `opencode/*` branch per numbered item below (or a stacked series), off `wave0-foundation`. Share back via fetch; Claude reviews each before merge.
**Origin:** your own second-pass audit `docs/audit/07-full-codebase-audit.md` (findings CR-A, CR-B, H-2, M-1/2/3, L-1) and `06-performance-audit.md` (concurrency). Two owner decisions are now made and baked in below.

## Lane boundaries (hard)
- You OWN `packages/replay` and `packages/experiments` for this phase. Claude stays out of those files to avoid conflicts.
- DO NOT touch `packages/schema/` or `fixtures/golden/` (owner+Claude only). If a fix seems to need a schema/contract change, STOP and flag it — don't edit it.
- `ReplayContext` / `ReplayedDecision` live in `packages/replay/backend.py` (NOT schema) — those are yours to extend.
- Keep the frozen `replay(trace, variant, from_turn)` signature (PRD §5). Extend additively.
- Every item ends green (`uv run pytest -q` from repo root) and adds the test named in its acceptance criteria.

## Work order (do in this order; each is a reviewable unit)

### 1. CR-A — replay prompt must include the pivot turn's caller utterance
**Bug:** `ReplayContext.turns_before` is only `turn_index < turn_idx` (`replay.py:118`) and `_render_messages` renders only `turns_before` (`openai_backend.py`). The pivot turn's own caller ASR — the utterance the decision responds to — is dropped. Measured: 30/30 turn-0 route prompts have zero conversational content. The model decides blind.
**Fix (additive):**
- Extend `ReplayContext` with the pivot turn's caller-side content — add a field e.g. `current_turn_asr: tuple[AsrTranscribe, ...]` (or the transcripts). Populate it in `replay.py` from the pivot turn's `.asr` when building the context for each target span.
- In `OpenAIBackend._render_messages`, after the `turns_before` messages, append the current turn's ASR transcript(s) as the final `user` message.
- PRD §8.1 pins the caller side of *every* turn — the pivot caller audio is fixed/known; the counterfactual agent decides *given* it. This is faithful, not leakage.
**Acceptance:** new test (experiments or replay) asserting the rendered prompt for a turn ≥ 0 contains that turn's caller transcript. MockBackend ignores messages, so also keep a mocked-client render assertion. Suite green.

### 2. CR-B — rate-arbitrage Δcost (owner decision: **rate-arbitrage**, NOT real-usage)
**Bug:** `_rebuild_llm_span` swaps in the REAL `decision.input_tokens/output_tokens` (`replay.py:91-92`), then `replay()` re-prices the whole trace. Real rendered prompts (~85 tok) are ~4.4× smaller than the corpus's synthetic `input_tokens` (~375), so `delta_cost = new − original` is negative **independent of the variant** and passes the §8.3 gate (`margin.py:24-26`) spuriously. Verified in code — a certainty, not a hypothesis.
**Fix — define the trial's `delta_cost` as rate arbitrage (deterministic), decoupled from the render:**
- For each REPLACED decision span, compute the Δ from the **original token counts** priced at the **routed model's rate** vs the **original model's rate**:
  `Δ_span = price(orig.input_tokens, orig.output_tokens, replayed.model) − price(orig.input_tokens, orig.output_tokens, orig.model)`
  where `replayed.model` is the model the variant routed to (`ReplayedDecision.model`). Sum over replaced spans → `delta_cost`. Same workload, different price — exactly MockBackend's semantics, and 0 when the variant doesn't reroute a span.
- Keep the trace-level `price_trace` result for the flame graph, but the **trial's `delta_cost`** must come from the decision deltas above, NOT from re-pricing the render-scaled rebuilt trace.
- REAL usage is still valuable but SEPARATE: compute a second figure `delta_cost_real_usage` = same formula but with the real `replayed.input/output_tokens` for the replaced spans, and surface it in the trial/result **explicitly labeled** "includes render-scale mismatch; not gated." (If adding a field to `Trial`/`ExperimentResult` requires a schema change — STOP and flag; otherwise carry it in the experiments-layer result dict, not the frozen schema.)
- `outcome_preserved` and latency come from the real calls, unchanged.
**Acceptance:** identity-replay sanity test — a mocked "real" backend that returns the ORIGINAL span's model + usage ⇒ trial `delta_cost ≈ 0` (any variant-invariant bias shows as systematic nonzero). Plus a test that a genuine reroute (gpt-5 → gpt-5-nano) yields the deterministic rate-arbitrage delta you'd hand-compute from `rates.yaml`. Suite green.

### 3. H-2 + M-1 — make `--paid` runnable non-interactively and fail before spend
- **H-2:** `run_experiments.py:82` `input()` raises `EOFError` without a TTY (this was likely the aborted smoke's "last-minute error"). Add `--yes` ("for scripted runs; the env gate `TURNSTILE_ALLOW_PAID=1` still applies"). When `--yes`, skip the prompt.
- **M-1:** validate BOTH `--out` and `--checkpoint` paths are writable (create parent + probe-write) **before** constructing the backend, so an unwritable path can never lose a paid run at the end (it already did once at n=2).
**Acceptance:** test that `--paid --yes` + env gate constructs the backend with no stdin; test that an unwritable `--out` aborts before any backend construction. Suite green.

### 4. M-2 / M-3 — minor correctness/cost
- **M-2:** `decision_chosen = raw completion text` (`openai_backend.py`). Either parse per `decision_kind` (escalate_check → escalate/continue containment; tool_select → tool name) OR document the field at the `ReplayedDecision` boundary as "utterance, not parsed decision." Lightweight; document is fine for now.
- **M-3:** add a generous `max_tokens` to the completion call (corpus output p95 < 200 tok; cap ~256) and log violations. Latency + cost lever.
- Also fix the 3 E402s the resilience commit introduced (`openai_backend.py` constants block between imports) — move the block below imports or `# noqa: E402`.
**Acceptance:** existing OpenAIBackend tests still green; the fake-client call asserts `max_tokens` is passed.

### 5. Lint merge (L-2)
Merge your `opencode/lint-hygiene` (`d862f0e`, 19 fixes incl. the `test_golden_shape.py` F821) into the line, plus the E402 follow-up from item 4. Ruff clean.

### 6. Change B — concurrency (your `06-performance-audit.md` §3 Option 1 / §6 design)
- **L-1 first:** make `CheckpointStore.put` thread-safe (a `threading.Lock` around the append+fsync).
- Split-and-compose per §3: extract the map (per-trace `replay`) / reduce (`aggregate_experiment`) additively in `packages/replay` WITHOUT changing the frozen `replay()` signature; put the concurrent driver in `packages/experiments` (`run_matrix_checkpointed` gains `max_workers: int = 1`, ThreadPoolExecutor over not-yet-checkpointed traces).
- Determinism: assemble trials in corpus order regardless of completion order → identical aggregates to the sequential path.
- The shared backend is fine under threads (OpenAI client is thread-safe; `replay` reads globals + builds local state). The `OpenAIBackend._calls` progress counter should be lock-guarded (also fixes interleaved prints).
**Acceptance:** test that `max_workers=8` yields byte-identical `ExperimentResult.model_dump()` to `max_workers=1` on a fixed corpus; test store-put under N threads → M unique valid lines, no interleaving corruption; default `max_workers=1` keeps all existing tests unchanged. Suite green.

### 7. (Owner-gated) Smoke #3 → n=250 — DO NOT run without explicit owner spend confirmation
After items 1–6 merge, the paid path is correct + fast. Smoke #3 = `--n 30 --seed 0 --paid --yes --workers 8`, routing-only (~$0.04). Report: real divergence rate (upper bound — see H-1), real RPM ceiling, real ETA. THEN n=250 (~$0.41). Each spend needs owner's explicit go — the env gate + `--yes` do not authorize spend on their own.

## Not in this brief (Claude/owner keeps)
- H-1 framing → METHOD.md / LIMITATIONS.md (accept+document per-evidence-source; structural preservation caveat; lead the real signal with divergence on decision-sensitive traces). The tool_select-sensitivity code upgrade is queued as an explicit **Wave-2 entry-criterion**, not built now.
- schema/fixtures, contract/narrative decisions, result interpretation, branch reviews + merges.
