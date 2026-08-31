# Audit Handoff — For Claude Code

**Author:** Antigravity (Claude Opus 4.6)  
**Date:** 2026-08-31 01:42 AM PDT  
**Context:** Full codebase audit performed while Claude Code was on break. No code was modified — read-only analysis.

---

## What Was Done

A GTM-level audit of all 6 implemented packages (`schema`, `pricing`, `detectors`, `verdict`, `otel`, `stats`) against the PRD, design spec, schema v1.1 amendment, and GATES.md. Four parallel review agents + manual cross-validation.

**Documents produced (read in order):**

1. [`01-code-review.md`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/docs/audit/01-code-review.md) — 13 findings (2 CRITICAL, 4 HIGH, 4 MEDIUM, 3 LOW)
2. [`02-architecture-audit.md`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/docs/audit/02-architecture-audit.md) — Dependency graph, contract integrity, 5 concerns
3. [`03-gap-analysis.md`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/docs/audit/03-gap-analysis.md) — 11 gaps mapped PRD→code with severity
4. [`04-risk-assessment.md`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/docs/audit/04-risk-assessment.md) — 10 risks with priority and mitigation
5. [`05-test-coverage.md`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/docs/audit/05-test-coverage.md) — 9 test gaps identified

---

## Top 5 Action Items (Prioritized)

### 1. FIX IMMEDIATELY — D7 Cartesian product (CR-01)

**File:** `packages/detectors/src/turnstile_detectors/d07_barge_in.py` L32-34  
**Bug:** Nested `for tts … for playback` cross-multiplies findings.  
**Fix:** `zip(turn.tts, turn.playback)` or index-matched pairing.  
**Add:** Guard for `tts.chars_synthesized == 0` (CR-03, L37).

### 2. FIX IMMEDIATELY — G2 fallback in recorder (CR-04)

**File:** `packages/otel/src/turnstile_otel/recorder.py` L410  
**Bug:** `chars_synthesized` defaults to `len(text)` (intended, not billed).  
**Fix:** Remove fallback. Require explicit `chars_synthesized`.

### 3. FIX SOON — Telephony cost dropped on edge cases (CR-05, CR-10)

**File:** `packages/pricing/src/turnstile_pricing/pricing.py` L111-123  
**Bug:** Zero-duration turns or zero turns cause telephony cost to vanish from `conv_cost`.  
**Fix:** Add fallback attribution + post-condition invariant check.

### 4. FIX SOON — D10 same-turn double-count (CR-08)

**File:** `packages/detectors/src/turnstile_detectors/d10_tool_thrash.py` L32-38  
**Bug:** Each duplicate in the same turn adds full `turn_cost`.  
**Fix:** Track attributed turns; add `turn_cost` only once per turn.

### 5. ADD TESTS — Three missing test cases

- `test_d07`: Multi-TTS/playback per turn (exposes CR-01)
- `test_d07`: `chars_synthesized == 0` (exposes CR-03)
- `test_pricing`: Zero-turn trace with telephony (exposes CR-05/CR-10)

---

## What NOT to Change Without Owner Approval

- **Schema contracts** — `Finding.span_id` type change (CR-13) affects all consumers
- **`detect()` signature** — Adding `rates` parameter (A2) changes the public API
- **Verdict labels** — `PARTIALLY_RESOLVED` (GAP-11) requires scenario registry

---

## Status at Time of Audit

- **Commit:** `f852980` (2026-08-30 23:27)
- **All 295+ tests:** PASSING
- **Working tree:** CLEAN (no uncommitted changes)
- **Packages complete:** schema, pricing, detectors, verdict, stats, dashboard
- **Packages remaining:** replay (critical path), agent (blocked by G1), caller (blocked by agent)
