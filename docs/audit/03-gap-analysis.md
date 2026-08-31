# Gap Analysis — PRD vs Implementation

**Auditor:** Antigravity (Claude Opus 4.6)  
**Date:** 2026-08-31  
**Method:** Systematic comparison of PRD §3–§8 requirements against implemented code  

---

## Gap Severity Legend

| Level | Meaning |
|-------|---------|
| **BLOCKING** | Cannot demonstrate the claimed capability |
| **MATERIAL** | Missing component weakens the commercial case |
| **ACCEPTABLE** | Documented limitation; does not invalidate results |

---

## Gap Register

### GAP-01 · Replay engine does not exist

**PRD Reference:** §8 (Counterfactual Replay)  
**Severity:** BLOCKING  
**Status:** Wave 2 — not started  

The replay engine is the core differentiator ("prove recoverable savings via counterfactual replay rather than speculative advice" — PRD §1). Without it:
- `Recoverable Margin %` cannot be computed from real data
- The demo's "340 replayed calls with 96.2% identical resolution and 41% cost reduction" (DEMO.md §3:00) must be fabricated
- `Trial` and `ExperimentResult` contracts exist in schema but have no producer

**Critical path:** This is the single most important missing component.

---

### GAP-02 · Live agent does not exist

**PRD Reference:** §3 (Agent Under Test), Layer 0  
**Severity:** BLOCKING (for production), ACCEPTABLE (for demo)  
**Status:** Wave 1 Opus lane — spike only  

`packages/agent/` contains only the `playback_probe.py` spike. No Pipecat pipeline, no scenarios, no live audio. For the demo, pre-computed fixtures substitute. For production/GTM, this is the entire top of the pipeline.

**Blocked by:** Gate G1 (recorder concurrency redesign)

---

### GAP-03 · Synthetic caller does not exist

**PRD Reference:** §8.4 (Corpus Generation)  
**Severity:** MATERIAL  
**Status:** Wave 2 — not started  

No `packages/caller/`. Cannot generate the 250–400 call corpus required for statistically significant experiments.

**Blocked by:** GAP-02 (live agent)

---

### GAP-04 · Gate G1 unresolved — D8 numbers are demo-only

**PRD Reference:** §3.2, GATES.md G1  
**Severity:** MATERIAL  
**Status:** Acknowledged in GATES.md; no code fix  

The `TraceRecorder` cannot emit overlapping spans. D8's silence tax figures on live traces will be systematically inflated. The golden-fixture numbers are correct (fixtures were hand-authored with overlap), but they prove the detector logic, not the measurement pipeline.

**Impact on demo:** None (fixtures are pre-computed).  
**Impact on GTM:** D8 waste numbers from production traffic are unreliable.

---

### GAP-05 · Escalation classifier missing — D9 Tier 1 understates waste

**PRD Reference:** §6 row 9  
**Severity:** MATERIAL  
**Status:** Documented in D9 module docstring as "KNOWN WEAKNESS"  

D9 Tier 1's `turn_of_no_return` equals the terminal handoff turn itself (from `adjudicate`), not the earlier turn where escalation intent first became visible. The PRD narrative ("predictable at turn 3, ran 9 more turns") is not recovered — `t` always equals the last turn, collapsing the waste figure to a single turn's cost.

The detector fires (positive waste), but the dollar figure is drastically understated — making the "Commercial Star" detector's headline number weak in a pitch.

---

### GAP-06 · No experiment runner or matrix execution

**PRD Reference:** §8.3 (6 variants × 250 traces)  
**Severity:** BLOCKING  
**Status:** Wave 3 — not started  

The `ExperimentResult` schema is defined, `aggregate_experiment` works, but there is no code to:
- Define the 6 variant specs
- Execute replay across the variant × trace matrix
- Serialize results for dashboard consumption

---

### GAP-07 · Baselines are sample-only, not calibrated

**PRD Reference:** §5, `Baselines` contract  
**Severity:** MATERIAL  
**Status:** `fixtures/sample/baselines.json` exists with hardcoded values  

D4 (turn inflation) relies on `Baselines.per_intent[scenario_id].p75_turns`. These baseline numbers are hand-authored for the fixtures, not derived from corpus data. The PRD requires baselines calibrated from the actual call corpus.

**Impact:** D4's waste figures are directionally correct but not statistically grounded.

---

### GAP-08 · No `METHOD.md` or `LIMITATIONS.md`

**PRD Reference:** DEMO.md §3:40 ("unprompted limitations")  
**Severity:** ACCEPTABLE  
**Status:** Wave 3 — not started  

The demo script calls for proactively stating limitations. No formal methodology or limitations document exists yet.

---

### GAP-09 · No LLM judge (verdict source 5)

**PRD Reference:** §7 evidence precedence source 5  
**Severity:** ACCEPTABLE  
**Status:** Stub in `_llm_judgment_stub()` returning `None`  

The verdict layer operates on deterministic sources 1–4 only. Source 5 (LLM tie-breaker) is a declared stub. The PRD requires 60 hand-labeled conversations + Cohen's κ ≥ 0.75 before activating it. This is Wave 3 scope.

**Impact:** Verdicts on edge cases (informational intents with no clear close) may be less accurate. The 23 fixtures don't exercise this gap because they have clear deterministic signals.

---

### GAP-10 · Cosine similarity for D3 not implemented

**PRD Reference:** §6 row 3 ("cosine(chunk, context) > 0.85 OR doc ID collision")  
**Severity:** ACCEPTABLE  
**Status:** Documented in D3 module docstring; only doc-ID overlap is implemented  

The embedding-based retrieval deduplication is deferred (requires an embedding model this wave doesn't have). Only the structural doc-ID half fires.

---

### GAP-11 · `PARTIALLY_RESOLVED` and `MISROUTED` verdicts never emitted

**PRD Reference:** §7 VerdictLabel enum  
**Severity:** ACCEPTABLE  
**Status:** Enum values exist but no adjudication path produces them  

`adjudicate()` never returns `PARTIALLY_RESOLVED` or `MISROUTED`. Verified empirically: all 7 fixtures with `expected_verdict: PARTIALLY_RESOLVED` in the manifest actually receive `RESOLVED` from `adjudicate()` (6 at confidence 0.7, 1 at 0.9). The test suite correctly handles this — only 8 spec-derivable verdicts are pinned; the other 15 accept any valid label. Implementing `PARTIALLY_RESOLVED` requires a scenario registry that can define partial slot completion criteria.

---

## Summary Matrix

| Gap | Severity | Blocks Demo? | Blocks GTM? | Dependency |
|-----|----------|-------------|-------------|------------|
| GAP-01 Replay | BLOCKING | Yes (data fabricated) | Yes | Pure Python; can build now |
| GAP-02 Live agent | BLOCKING | No | Yes | Gate G1, WSL2, audio |
| GAP-03 Synthetic caller | MATERIAL | No | Yes | GAP-02 |
| GAP-04 Gate G1 | MATERIAL | No | Yes | Recorder redesign |
| GAP-05 Escalation classifier | MATERIAL | No | Weakens D9 | Verdict + classifier |
| GAP-06 Experiment runner | BLOCKING | Yes (data fabricated) | Yes | GAP-01 |
| GAP-07 Baselines calibration | MATERIAL | No | Yes | Corpus |
| GAP-08 METHOD/LIMITATIONS docs | ACCEPTABLE | Partial | Yes | Knowledge only |
| GAP-09 LLM judge | ACCEPTABLE | No | Partial | 60 labels + calibration |
| GAP-10 Cosine similarity | ACCEPTABLE | No | No | Embedding model |
| GAP-11 Partial/Misrouted verdicts | ACCEPTABLE | No | No | Scenario registry |

---

## Critical Path

```
Gate G1 → Live Agent → Synthetic Caller → Corpus → Baselines Calibration
                                              ↘
                                         Replay Engine → Experiment Runner → Dashboard Wiring → Demo
```

The replay engine (GAP-01) is the only BLOCKING item that can be built NOW with no external dependencies. It is pure Python, operating on existing `Trace` + `VariantSpec` contracts.
