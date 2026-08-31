# Test Coverage Analysis — Turnstile Profiler

**Auditor:** Antigravity (Claude Opus 4.6)  
**Date:** 2026-08-31  
**Scope:** All test files across 6 packages + fixture coverage  

---

## Test Inventory

| Package | Test Files | Test Count (approx) | Status |
|---------|-----------|---------------------|--------|
| `schema` | 7 files (`test_smoke`, `test_enums`, `test_rates`, `test_spans`, `test_trace`, `test_contracts`, `test_fixtures`) | ~80 | All pass |
| `pricing` | 1 file (`test_pricing`) | ~25 | All pass |
| `detectors` | 13 files (`_builders`, `test_contract`, `test_d01`–`test_d10`, `test_fixture_sweep`) | ~120 | All pass |
| `verdict` | 1 file (`test_adjudicate`) | ~25 | All pass |
| `otel` | 3 files (`test_recorder`, `test_otel_export`, `test_golden_shape`) | ~30 | All pass |
| `stats` | 1 file (`test_stats`) | ~15 | All pass |
| **Total** | **26 files** | **~295+** | **All pass** |

---

## Coverage Strengths

### CS-1 — Fixture sweep provides regression backbone

[`test_fixture_sweep.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/tests/test_fixture_sweep.py) dynamically iterates all 23 golden fixtures against all 10 detectors, verifying:
- Target detectors fire on their designated fixture
- Target detectors are silent on non-designated fixtures (negative coverage)

This is the strongest single test in the suite — it catches regressions in detector logic AND fixture shape simultaneously.

### CS-2 — Schema validation is thorough

`test_spans.py` validates all 8 span types including the critical `ToolCall` effect validator. `test_fixtures.py` round-trips every golden fixture through schema validation. This means the fixtures ARE the contract — any schema change that breaks a fixture breaks the build.

### CS-3 — Verdict tests cover all 23 fixtures

`test_adjudicate.py` runs `adjudicate()` on every fixture and checks the expected verdict label from `manifest.yaml`. This is comprehensive positive coverage.

---

## Coverage Gaps

### TG-01 · No negative test for D5 with different slots

**Package:** `detectors`  
**File:** `test_d05_reprompt_loop.py`  
**Severity:** HIGH  
**Gap:** No test for consecutive `slot_fill` decisions with **different** `decision_chosen` values (e.g., "name" → "address"). A broken detector that fires on ANY consecutive slot_fills (ignoring `decision_chosen` equality) would pass all current tests.  
**Fix:** Add `test_silent_on_different_slot_fill_decisions()`.

---

### TG-02 · No test for zero-turn traces in pricing

**Package:** `pricing`  
**File:** `test_pricing.py`  
**Severity:** MEDIUM  
**Gap:** No coverage for `turns=[]`. Tests always provide at least one turn. `price_trace` with zero turns + telephony leg silently drops telephony cost (see CR-05/CR-10).  
**Fix:** Add `test_zero_turn_trace_with_telephony()`.

---

### TG-03 · No test for D7 with multiple TTS/playback spans per turn

**Package:** `detectors`  
**File:** `test_d07_barge_in.py`  
**Severity:** HIGH  
**Gap:** Golden fixtures have 1:1 TTS-to-playback per turn. The Cartesian product bug (CR-01) is latent because no test exercises the multi-span case.  
**Fix:** Add `test_multi_tts_playback_per_turn()` — inject 2 TTS + 2 playback spans, verify findings count matches span count (not the Cartesian product).

---

### TG-04 · No test for D7 with `chars_synthesized == 0`

**Package:** `detectors`  
**File:** `test_d07_barge_in.py`  
**Severity:** MEDIUM  
**Gap:** `ZeroDivisionError` on `chars_synthesized == 0` (CR-03) has no test.  
**Fix:** Add `test_zero_chars_synthesized_no_crash()`.

---

### TG-05 · No integration test across pipeline stages

**Package:** (repo-level)  
**Severity:** MEDIUM  
**Gap:** Each package tests in isolation. No test runs `price_trace → adjudicate → detect` end-to-end on a fixture and validates the combined output.  
**Fix:** Add `tests/test_integration.py` at repo root.

---

### TG-06 · Pricing `conv_cost` invariant not asserted

**Package:** `pricing`  
**File:** `test_pricing.py`  
**Severity:** MEDIUM  
**Gap:** Tests check `sum(pt.turn_costs) == pytest.approx(pt.conv_cost)` but do not verify `sum(stage_costs.values()) == conv_cost`. The telephony attribution bug (CR-05) would be caught if this invariant were tested with zero-duration turns.  
**Fix:** Add invariant assertion to existing tests: `assert sum(pt.stage_costs.values()) == pytest.approx(pt.conv_cost)`.

---

### TG-07 · Tautological test for TTS/playback gap

**Package:** `schema`  
**File:** `test_spans.py` L145–158  
**Severity:** LOW  
**Gap:** `test_tts_and_playback_gap_is_representable` asserts `184 > 61` — a tautology. It proves Python's `>` works, not that the schema enforces any relationship between `chars_synthesized` and `chars_played`.  
**Impact:** Gives false coverage confidence. The schema does NOT enforce `chars_played <= chars_synthesized`, and this test doesn't reveal that.  
**Fix:** Either add a real validator (`chars_played <= chars_synthesized`) and test it, or remove the tautological assertion.

---

### TG-08 · Zero-token LLM span not tested in D6

**Package:** `detectors`  
**File:** `test_d06_dead_tokens.py`  
**Severity:** LOW  
**Gap:** No test for `output_tokens=0` with non-empty `output_text`. Could cause zero-dollar waste (mathematically correct but semantically odd — 0 tokens that were "wasted").  
**Fix:** Add edge case test.

---

### TG-09 · No FALSE_RESOLVE test for failed handoffs

**Package:** `verdict`  
**File:** `test_adjudicate.py`  
**Severity:** MEDIUM  
**Gap:** No fixture or unit test exists where a handoff fails (`effect=rejected`) AND the agent asserts completion. The CR-07 bug (verdict skips FALSE_RESOLVE check for handoffs) is untested. Note: the verdict test design is sound — `PINNED` (L36–45) only contains the 8 spec-derivable fixtures; `PARTIALLY_RESOLVED` fixtures are correctly left unpinned, accepting any valid label.  
**Fix:** Add a unit test `test_rejected_handoff_with_completion_assertion_is_false_resolve()` alongside the existing `test_rejected_handoff_is_unresolved_not_escalated()`.

---

## Fixture Coverage Matrix

| Fixture ID | schema | pricing | detectors | verdict | otel |
|-----------|--------|---------|-----------|---------|------|
| 00–22 (all 23) | ✅ validated | ✅ priced | ✅ swept | ✅ adjudicated | ✅ shape-tested |

All 23 fixtures are exercised by all relevant packages. The fixture coverage is excellent.

---

## Summary

| Category | Count | Verdict |
|----------|-------|---------|
| Tests passing | 295+ | ✅ |
| Fixture coverage | 23/23 | ✅ Excellent |
| Negative test coverage | Adequate for most detectors | ⚠️ D5 gap |
| Edge case coverage | 3 material gaps | ⚠️ TG-02, TG-03, TG-04 |
| Integration coverage | None | ❌ TG-05 |
| Tautological tests | 1 identified | ⚠️ TG-07 |
| **Total gaps** | **9** | |

The test suite is strong for fixture-based validation but has blind spots on production edge cases (multi-span turns, zero-duration turns, zero-token spans). The missing integration test (TG-05) is the most impactful gap — it's the only test shape that would catch a contract mismatch between pipeline stages.
