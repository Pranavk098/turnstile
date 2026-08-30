# Turnstile Schema v1.1 Amendment

**Date:** 2026-08-30
**Status:** Approved by Pranav (schema owner) — pending implementation
**Authority:** The PRD reserves frozen-contract changes to the human. Both changes below are authorized by the schema owner. This amendment supersedes the affected parts of `turnstile-prd.md` §3/§6/§7 and bumps `turnstile.schema_version` from `1.0` → `1.1`.
**Origin:** Surfaced by the Opus fixture review (Wave 0, Task 8+9) as tensions T1 and T3; resolved by owner decision.

Both changes are **additive with defaults** (existing v1.0 fixtures still validate), but they are deliberate semantic amendments, so the version bumps to 1.1.

---

## Change T3 — ToolCall: split transport from effect

**Problem.** PRD §7 makes *terminal tool state* the #1 verdict-evidence source ("a refund either executed or did not"). The v1.0 `tool.call` span exposed only `result_hash` (opaque) and no notion of business effect. A refund tool can return HTTP 200 with `{"status":"pending_review"}` — the call succeeded, the refund did **not** happen. If the agent then says "your refund is processed," that is a textbook FALSE_RESOLVE (§7, the most expensive failure), and a single call-success boolean misses it entirely.

**Two orthogonal axes added to `tool.call`:**

```jsonc
"turnstile.tool_status": "ok" | "error",          // CALL level: did the invocation complete (vs 5xx/timeout/exception). default "ok"
"turnstile.effect": "committed" | "pending" | "rejected" | "none" | "unknown"  // EFFECT level: did the intended mutation take. default "none"
```

Mapping (the `process_refund` example):

| Tool response | tool_status | effect |
|---|---|---|
| `{"status":"processed"}` | ok | committed |
| `{"status":"pending_review"}` | ok | pending |
| `{"status":"declined"}` | ok | rejected |
| 500 / timeout after send | error | unknown |
| `lookup_order` (read) | ok | none |

`result_hash` is **retained** (Detector 10 tool-thrash still dedupes by identical result) but is no longer verdict-load-bearing.

### Validator rule (enforced in the schema; makes fixtures self-checking at contract-test time)

```
tool_kind ∈ {mutation, handoff}  → effect ∈ {committed, pending, rejected, unknown}
tool_kind ∈ {lookup, retrieval}  → effect = none
tool_status = error              → effect ∈ {rejected, none, unknown}     # a failed call cannot have committed/pending
```

**`handoff` is mutation-like — the full enum, deliberately.** A handoff has the same four terminal states as any mutation, and the two that a "did-it-complete" boolean would erase are the most expensive in a contact center: `pending` = transfer initiated, caller sitting in a queue waiting for an available human (queue time is real and often long — collapsing it into `committed` claims completion while the caller is still on hold); `rejected` = no agents available / after-hours / queue at capacity — the AI tried to hand off and couldn't, and the caller is stranded after paying the full conversation cost. A rejected handoff is the worst single outcome in the taxonomy; the enum must be able to say it.

Implement as a Pydantic `model_validator(mode="after")` on `ToolCall`. A fixture that violates the relationship fails `contract-test`.

### Verdict-layer consequences (Wave 1 `verdict/` design constraints — not schema, but binding)

- **Deterministic FALSE_RESOLVE:** agent asserts completion for intent X **and** the mutation bound to X has `effect ∈ {pending, rejected}` (or `tool_status = error`) ⇒ `FALSE_RESOLVE`. No hash-parsing, no LLM judgment for this case.
- **RESOLVED requires** `effect = committed` on the intent's terminal required mutation.
- **ESCALATED requires `handoff.effect = committed`.** A `rejected` handoff is `UNRESOLVED`, not `ESCALATED`, and a `pending` handoff (caller queued, still on hold) is not yet `ESCALATED` either. Vendors habitually count every escalation as a clean outcome; a *failed* escalation is a stranded caller who paid full cost and must never land in the same bucket. Worth a sentence in the demo.
- **Detector 9 (escalation debt) gains a second tier.** Tier 1 (existing): spend before an *inevitable* handoff. Tier 2 (new): spend before a handoff that then **failed** (`effect = rejected`) — the full conversation cost **plus a lost customer**, the single most damning number the tool can produce. This is exactly what justifies the `escalation_policy` replay variant: if rejection is predictable (after-hours, queue depth), fail over to a callback at turn 3 instead of burning to turn 14 and stranding the caller.
- **`unknown` blocks confident verdicts** (the calibration demo line): if any *required* mutation resolves to `effect = unknown`, then
  - `verdict.confidence` is capped at **0.6**,
  - the label may **not** be `RESOLVED` or `FALSE_RESOLVE`,
  - `evidence` records the ambiguity explicitly.
  The judge declines to fabricate a verdict when the underlying evidence is genuinely ambiguous — the opposite of what an always-answering LLM judge does.

### Ground truth stays out of the trace

`expected_verdict` lives in `fixtures/golden/manifest.yaml` as **test metadata**, never in the `Trace` schema. Ground truth in the trace would let the verdict layer cheat in development, and production traces will never carry it. Answer keys belong in fixtures, not the data format.

---

## Change T1 — every span gets absolute offsets; Detector 8 restated

**Problem.** PRD §6 Detector 8 keys on "inter-span gaps > 200ms with no audio flowing." In a competent voice pipeline TTS streams *while* the LLM is still generating and playback overlaps the next compute — that overlap is the core engineering of voice. With only per-span `latency_ms`/durations you can only **sum**, and summing double-counts concurrency: you cannot tell whether an 800ms LLM call happened during playback (free) or during dead air (billed). The v1.0 residual produces a number that is wrong in the exact direction any voice engineer catches immediately.

**Two fields added to the base `Span` (every span type inherits them):**

```jsonc
"turnstile.start_offset_ms": 0,   // milliseconds from conversation start
"turnstile.duration_ms": 0        // the span's wall extent
```

These are natively produced by OTel span start/end times — this exposes a field the tracer already has, not a new measurement. For `audio.playback` truncated by barge-in, `duration_ms` is the *actual played* extent. `latency_ms` on `llm.decide`/`tool.call` is retained (semantic "model/tool latency"); `duration_ms` is the timeline extent (typically equal for compute spans).

### Detector 8 restated (Wave 1 `detectors/` design constraint)

```
active_ms(turn)  = | UNION of [start_offset, start_offset + duration) across
                    asr, llm.decide, tool.call, tts, audio.playback |   # union, NOT sum — overlap is free
silence_ms(turn) = billed_wall_ms − active_ms
cost_silence     = silence_ms / 1000 × telephony_rate_per_second
attribution      = label each maximal gap by the span that STARTS NEXT
                   (model | tool | asr_endpoint | tts_ttfb)
```

**Invariant test (free correctness check, README line):** the v1.0 residual formula (`billed_wall − sum(covered audio/compute)`) and the offset-gap union formula must agree on non-overlapping fixtures; where they diverge, the divergence is exactly the concurrency the union captures and the sum double-counts. Keep both; assert agreement on the fixtures with no overlap.

---

## Fixture & contract-test impact

- **All fixtures** gain `start_offset_ms`/`duration_ms` on every span (regenerated via the authoring scripts). Author realistic timelines, and give **at least two** fixtures genuine TTS/LLM **overlap with different overlap shapes** — a single overlap case can pass against a subtly wrong union implementation; two different shapes will not.
- **Fixture 17 (`false_resolve`)** → `process_refund` mutation with `tool_status = ok`, `effect = rejected`, agent `output_text` asserting "processed."
- **THREE new effect-driven fixtures** (new `effect_edge` manifest category):
  - `unknown_mutation` — a required mutation at `effect = unknown` (timeout after send); tests the verdict confidence-cap (≤0.6, not RESOLVED/FALSE_RESOLVE).
  - `handoff_rejected` — `tool_kind=handoff`, `effect=rejected` (no agents/after-hours); expected verdict `UNRESOLVED` (not ESCALATED), and exercises Detector 9 tier 2 (spend-before-failed-handoff).
  - `handoff_pending` — `tool_kind=handoff`, `effect=pending` (caller queued/on hold); expected verdict not ESCALATED.
- **Manifest** gains `expected_verdict` per fixture (test metadata).
- **contract-test**: update `REQUIRED_DISTRIBUTION` (20 → **23**; `effect_edge: 3`); add a test asserting the `effect × tool_kind × tool_status` validator rejects an illegal combination (incl. a `handoff` with `effect=none`, now illegal); add the D8 residual-vs-union invariant test.
- Baseline `00` mutation (if any) → `effect = committed`. Escalation fixtures 09/14/15 → `handoff.effect = committed` (successful transfers, correctly ESCALATED).

## PRD sections to update to v1.1

- §3.1/§3.2 — add `start_offset_ms`/`duration_ms` to span attributes; add `tool_status`/`effect` to `tool.call`; note `result_hash` demoted.
- §6 Detector 8 — replace the gap rule with the union formula + attribution.
- §6 Detector 9 — add tier 2 (spend before a `rejected` handoff) alongside the existing inevitable-handoff tier.
- §7 — terminal-tool-state evidence now reads `effect`; add the `unknown` confidence-cap rule; `ESCALATED` requires `handoff.effect = committed` (rejected → `UNRESOLVED`, pending → not yet ESCALATED).
- Bump `turnstile.schema_version` default to `1.1`.

## Execution

This amendment is a small spec → plan → execute cycle to run **subagent-driven when the Claude spend limit resets**: (1) schema fields + `ToolCall` validator + `Span` offsets + version bump (TDD); (2) regenerate all fixtures with timelines + the new unknown fixture + fixture 17 change; (3) contract-test distribution + validator + invariant tests; (4) PRD edits. It slots between Wave 0 and Wave 1 — Wave 1 detectors (esp. D8) and the verdict layer consume the v1.1 contract.
