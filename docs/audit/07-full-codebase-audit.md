# Full Codebase Audit (second pass) — Turnstile

**Author:** GLM 5.3 (OpenCode), 2026-08-31. Read-only; benchmarks and reproduction scripts were run, no production code modified.
**Scope:** all 11 packages at `wave0-foundation` @ `bb7d0f4`, with emphasis on the paid-run path (`replay` → `experiments` → `OpenAIBackend`) that was exercised by the partial smoke runs. Predecessor: `01-code-review.md`…`05-test-coverage.md` (Antigravity/Opus 4.6). Performance/parallelization analysis is in `06-performance-audit.md`; progress/GTM distance in `08-progress-and-gtm-gap.md`.
**Baseline health at audit time:** workspace suite **545 tests, all green** (exit 0); ruff **22 findings** (19 already fixed on the unmerged `opencode/lint-hygiene` branch, +3 new E402s in `openai_backend.py` introduced by the resilience commit — constants block between imports, `openai_backend.py:37–43`).

---

## 0. Verdict up front

The analysis instrument (schema → pricing → verdict → detectors → replay → stats → dashboard) remains solid: **all five audit-fix-batch findings from the first audit are verified still fixed**, the new guard/manifest/checkpoint work is genuinely good engineering, and the free path runs end-to-end cleanly (verified: `run_experiments.py --n 5` produces manifest + checkpoint + margin + results). But this pass found **two critical paid-run validity defects and one structural-metric problem in the headline itself** that the golden fixtures and MockBackend cannot catch — they live exactly on the seam the fixtures never exercise: *real model output meeting synthetic corpus data*. They must be resolved before the next dollar is spent, or the Tier-1 headline will be precise, fast, and wrong.

---

## 1. Previous findings — re-verified (all FIXED, no regressions found)

| ID | Fix location | Status |
|---|---|---|
| CR-01 D7 cross-product | `d07_barge_in.py` — `zip(turn.tts, turn.playback)` | ✓ in place |
| CR-04 G2 fallback | `recorder.py` `record_tts` — `chars_synthesized` required, no `len(text)` fallback; survives the G1 rewrite | ✓ in place |
| CR-05/10 telephony drop | `pricing.py` fallback attribution | ✓ in place |
| CR-08 D10 double-count | `d10_tool_thrash.py` — `turn_cost_attributed: set` | ✓ in place |
| CR-03 chars_synth==0 test | present | ✓ |

Deferred minors carried over: pricing post-condition is still a bare `assert` (`pricing.py:143`) — stripped under `python -O`; lint debt (see header).

## 2. NEW findings — severity-ranked

### CR-A (CRITICAL, blocks paid-run validity): the replay prompt omits the caller utterance the decision responds to

`ReplayContext.turns_before` is turns with `turn_index < turn_idx` (`replay.py:118`), and `_render_messages` renders **only** `turns_before` (`openai_backend.py:59–64`). The current turn's caller side — the pinned ASR transcript the agent is responding to — is never included. **Measured:** for all 30 corpus traces at seed 0, the turn-0 `route` replay prompt contains **zero conversational content** (system line only; `turns_before` is empty at turn 0 and the pivot turn's own ASR is dropped). Every replayed decision is made blind — the model is asked "Make the 'route' decision for this turn" with nothing to decide from.

PRD §8.1 pins the caller side *of every turn* — the pivot turn's caller audio is fixed and known; the counterfactual agent decides *given* it. Fix (additive, `packages/replay`): extend `ReplayContext` with the target turn's caller-side spans (or its ASR transcripts) and render them as the final user message. MockBackend never reads messages, which is why 38 replay tests + all fixtures passed anyway.

### CR-B (CRITICAL, blocks headline validity): Δcost carries a ~4.4× token-scale artifact that biases every variant toward "savings"

The corpus's `llm.decide.input_tokens` are its synthetic context sizes (mean **375**, p50 304, max 1,066 — measured). The real backend's rendered prompts are mean **~85 tokens** (est., ~4 chars/token). Real `usage.prompt_tokens` therefore come back ~4× smaller than the synthetic `input_tokens` they replace, and `replay()` re-prices the rebuilt trace wholesale (`replay.py:146`, `:151`) — so `delta_cost = new − original` is strongly negative **independent of the variant**. The §8.3 gate (`margin.py:24–26`: preservation ≥ 0.95 **and** CI-upper < 0) would pass on this artifact, and `recoverable_margin` would report render mismatch as "proven savings." Neither smoke completed far enough to observe this — it is a code-level certainty, not a hypothesis.

Fix options (owner decision, must land before n=250):
1. **Recommended — rate-arbitrage Δcost:** compute the routed decision's Δcost deterministically by re-pricing the ORIGINAL span's token counts at the routed model's rate ("same workload, different price" — exactly MockBackend's semantics), and use the real calls to measure **outcome preservation and observed latency**, which is what only a real backend can measure. Report the real-usage Δ separately, labeled as including render-scale mismatch.
2. Prompt-scale anchoring (pad the render to the original context size) — keeps "real usage" Δcost but adds artificial tokens to every paid call; more spend, more distortion.
3. Per-decision Δcost restricted to replaced spans (both options imply this; full-trace re-price then only re-prices pinned-identical spans, which is a no-op for them — keep the trace-level price for the flame graph, compute the trial's Δcost from the decision deltas).

### H-1 (HIGH, metric integrity): outcome-preservation is structurally near-vacuous for mutation/handoff intents

Verdict labels are dominated by Evidence source 1 — the terminal tool's `effect` (`adjudicate.py:205–244`) — and replay **pins tools** (`_tool_cache` re-serves the trace's own tool spans, `replay.py:134`, `:141`; the real backend never proposes tools at all, `decision_chosen` is raw text and nothing consumes it in the trial path). Therefore, for any trace whose verdict is tool-effect-driven, `outcome_preserved` is **true by construction** — the model re-deciding text cannot move the label. The ledger's own smoke diagnostic ("100% preservation = RED FLAG", `progress.md:178`) would fire on every mutation/handoff trial, not because the variant isn't applied but because the metric cannot see it. The only label-sensitivity channels are the keyword heuristics (source 3 clean-close, `adjudicate.py:93–96`; FALSE_RESOLVE assertion, `:84–89`) — and a real model is *more* assertive than the corpus's canned register, so the flips it does produce are noise, not signal.

Options: (a) accept + document, reporting preservation per evidence-source; (b) give `tool_select` replays the ability to propose different tools/args, with the documented cache-miss → divergence path (`backend.py:70–78` already specifies it, unimplemented); (c) the Wave-2 LLM judge. Minimum for an honest demo: (a) with the sensitivity channels named; (b) is the credibility upgrade.

### H-2 (HIGH, blocks non-interactive paid runs): `input()` confirmation raises EOFError without a TTY

`run_experiments.py:82` — a background/CI/non-interactive `--paid` run dies at the confirmation prompt (`EOFError`). The env-var gate (`TURNSTILE_ALLOW_PAID=1`) is the real authorization; the interactive confirm is a second lock that cannot be satisfied non-interactively. Add `--yes` (documented as "for scripted runs; the env gate still applies"). This is almost certainly one of the "last-minute errors" in the aborted smoke attempt.

### M-1 (MEDIUM): no fail-before-spend writability check on outputs

`--out`/checkpoint paths are only touched at the end (`run_experiments.py:117`) or on first `store.put`. The n=2 integration probe completed ~144 paid calls and then lost the JSON to an unwritable path (ledger `:179`). Checkpointing now protects trials, but `results.json` is still write-at-end: validate both paths (create parent, probe-write) **before** the backend is constructed.

### M-2 (MEDIUM): `decision_chosen = raw completion text` (`openai_backend.py:123`)

Benign today — verified `adjudicate` never reads `decision_chosen` — but it is semantically wrong (a decision *label* set to an utterance) and becomes load-bearing the moment anything consumes it (e.g., H-1 option b, or any future detector on replayed spans). Either parse per `decision_kind` (escalate_check → {"escalate","continue"} containment; tool_select → tool name) or document the field as "utterance, not parsed decision" at the `ReplayedDecision` boundary.

### M-3 (MEDIUM): no `max_tokens` bound on completions (`openai_backend.py:102–104`)

Unbounded completion length on a reasoning model inflates both latency and cost. Cap generously (corpus output p95 is well under 200 tokens) and log violations — this is also a latency lever (06-performance §5.2).

### L-1 (LOW): `CheckpointStore` is not thread-safe yet — a prerequisite, not a bug

`put` opens/appends/fsyncs per trial with no lock (`checkpoint_runner.py:61–67`). Safe today (single-threaded runner); must be locked before Change B (06-performance §6.1).

### L-2 (LOW): lint debt — 22 findings

19 are fixed on the unmerged `opencode/lint-hygiene` branch (including the `test_golden_shape.py` F821, which exists at this tip); the resilience commit added 3 new E402s in `openai_backend.py` (`:37–43` constants between imports — add the same `# noqa: E402` treatment or move the block). Merge lint-hygiene + a 3-line follow-up.

### L-3 (LOW): `estimate_cost` duplicates `_earliest_applicable_turn`

Documented, deliberate duplication (`cost_estimate.py:27–37`); fine, but the guard's introduction is the moment to consider exporting the rule from `replay` instead.

## 3. Test-coverage gaps (paid-run path)

1. **Render completeness:** a test asserting the rendered prompt for a turn ≥ 1 contains that turn's caller transcript — would have caught CR-A.
2. **Identity-replay cost sanity:** a mocked-client test where the "real" backend returns the ORIGINAL span's usage and model — asserting trial Δcost ≈ 0. Would have caught CR-B (any variant-invariant bias shows up as a systematic nonzero).
3. **Non-interactive --paid:** a test that `--paid --yes` + env gate constructs the backend without stdin (would catch H-2).
4. **Concurrency:** store-put under threads (N workers × M puts → M unique lines, no interleaving corruption); progress counter exactness under threads.
5. **Divergence-mechanism test:** a fake backend returning a low-similarity pivot text → trial `status="divergent"`, excluded from Δcost aggregates (the gate exists in code, `replay.py:127–129`, but no test at the experiments layer exercises it end-to-end).

## 4. Architecture notes (no action required)

- Lane boundaries held: this pass touched no production code; the findings are specified, not implemented — `packages/replay` and `packages/experiments` changes remain in the owner/Claude lane per HANDOFF §3.
- The guard/manifest/checkpointing trio (`bb7d0f4`) is the right shape: fail-loud on unexecutable variants, reproducibility recorded before spend, per-trial persistence with torn-line tolerance. The recommended concurrency design (06-performance §3 Option 1) extends it without breaking the frozen `replay()` signature.
- `packages/schema` and `fixtures/golden` were not modified by anything since the first audit — ownership rule intact.

## 5. Recommended order of work (before the next dollar)

1. CR-A render fix (+ test) — small, `packages/replay`, no spend.
2. CR-B Δcost definition decision + implementation (+ identity-replay sanity test) — owner decision first (§2 CR-B options), then small.
3. H-1 framing decision (accept+document vs tool_select sensitivity) — owner; affects METHOD.md and the demo line.
4. H-2 `--yes` + M-1 fail-before-spend (+ tests) — trivial.
5. Merge `opencode/lint-hygiene` + E402 follow-up (L-2).
6. Change B concurrency per 06-performance §3/§6 (store lock, split-and-compose).
7. Smoke #3: n=30, routing-only, k=8, checkpoint + manifest → real divergence rate, real RPM ceiling, real ETA. Only then n=250.
