# Risk Assessment — Turnstile Profiler

**Auditor:** Antigravity (Claude Opus 4.6)  
**Date:** 2026-08-31  
**Scope:** Technical, commercial, and operational risks for GTM readiness  

---

## Risk Severity Legend

| Level | Meaning |
|-------|---------|
| **P0** | Will cause demo failure or provably wrong numbers in production |
| **P1** | Undermines credibility under scrutiny (VC due diligence, CTO eval) |
| **P2** | Limits product scope or delays GTM timeline |
| **P3** | Manageable with documentation or minor effort |

---

## Risk Register

### R1 — Detector waste figures are inflatable under production traffic

**Severity:** P0  
**Likelihood:** HIGH  
**Source:** CR-01, CR-04, CR-08 (code review)

Three independent inflation vectors:
1. **D7 Cartesian product** (CR-01): Multi-span barge-in turns multiply waste findings
2. **G2 fallback** (CR-04): `len(text)` substituted for billed chars inflates D7
3. **D10 same-turn double-count** (CR-08): Turn cost counted per duplicate, not per turn

**Impact:** A CTO who reproduces these inflated numbers on their own traces will lose trust immediately. "Your tool says I'm wasting \$0.60/call, but when I check, it's \$0.12" is a deal-killer.

**Mitigation:** Fix CR-01, CR-04, CR-08 before any external demo. These are localized code fixes, not architectural changes.

---

### R2 — Demo numbers are fabricated, not derived

**Severity:** P1  
**Likelihood:** CERTAIN (by design)  
**Source:** GAP-01, GAP-06 (gap analysis)

The demo script references specific numbers:
- "\$1.34 call" (DEMO.md §0:00)
- "\$0.19 barge-in waste" (§0:45)
- "41% cost reduction" (§3:00)
- "340 replayed calls, 96.2% identical resolution" (§3:00)

Without the replay engine and experiment runner, these are hand-authored in `dashboard/sample/*.json`. This is standard for a prototype, but if a VC asks "show me the pipeline that produced these numbers end-to-end," there is no pipeline.

**Mitigation:** Build the replay engine and experiment runner. Alternatively, be transparent: "these are from our 23-fixture validation suite; production corpus pending."

---

### R3 — D8 silence tax will over-report on live traffic

**Severity:** P1  
**Likelihood:** CERTAIN  
**Source:** Gate G1, GAP-04 (architecture audit)

On recorder-produced traces, `union == sum` because spans cannot overlap. D8's formula `silence_ms = billed_wall_ms - union(active_spans)` will therefore report more silence than actually exists. The magnitude of the error depends on how much real-world concurrency (TTS-during-LLM, cross-turn overlap) the recorder strips out.

**Impact:** A voice-AI CTO who knows their pipeline has concurrent stages will spot the discrepancy. "Your silence tax is 2x what it should be because you're not accounting for TTS streaming during LLM generation."

**Mitigation:** Gate G1 must land before showing D8 numbers on live traces. For the demo, fixture-derived numbers are correct (fixtures were hand-authored with overlap).

---

### R4 — D9 headline number is structurally weak

**Severity:** P1  
**Likelihood:** HIGH  
**Source:** GAP-05 (gap analysis), D9 KNOWN WEAKNESS

D9 is labeled "Commercial Star" in the PRD — the detector that shows "you spent \$0.41 on 9 unnecessary turns before an inevitable escalation." But `turn_of_no_return` currently equals the terminal handoff turn, not the turn where escalation became predictable.

**Impact:** The demo can show the narrative (fixture 09 is hand-authored), but any scrutiny of the actual dollar figure reveals it's just the last turn's cost, not the promised "turns 3–12 were all wasted."

**Mitigation:** Build an escalation classifier that sets `turn_of_no_return` to the earliest `escalate_check` decision, or compute it as the first turn where a live classifier's probability exceeds a threshold. This is a Wave-2/3 item.

---

### R5 — No production-calibrated baselines

**Severity:** P2  
**Likelihood:** HIGH  
**Source:** GAP-07 (gap analysis)

D4 (turn inflation) uses hardcoded baselines from `fixtures/sample/baselines.json`. These are plausible but not derived from real call distributions. A CTO will ask: "Where did these p50/p75 turn counts come from?"

**Mitigation:** After the synthetic corpus is generated (Wave 2), compute baselines from the corpus itself. Document the methodology in METHOD.md.

---

### R6 — Pricing invariant can break silently

**Severity:** P2  
**Likelihood:** LOW (requires edge cases)  
**Source:** CR-05, CR-10 (code review)

The pricing engine guarantees `Σ span_costs + telephony = conv_cost`, but two edge cases break it:
1. All turns have zero duration → telephony not attributed (CR-05)
2. Zero turns + telephony leg → telephony in `stage_costs` but not `conv_cost` (CR-10)

Both are uncommon in golden fixtures (which have well-formed durations), but possible on malformed live data.

**Mitigation:** Add invariant assertion: `assert abs(sum(stage_costs.values()) - conv_cost) < 1e-9` as a post-condition in `price_trace`. Fix the edge cases per CR-05/CR-10.

---

### R7 — CWD-dependent rate loading breaks deployment

**Severity:** P2  
**Likelihood:** MEDIUM  
**Source:** A2 (architecture audit)

Detectors load `pricing/rates.yaml` relative to `os.getcwd()`. Works in the repo. Breaks in deployment, notebooks, or any non-repo-root execution context.

**Mitigation:** Pass `RateTable` as a parameter to `detect()`, matching the pattern `price_trace(trace, rates)` already uses.

---

### R8 — No integration test between pipeline stages

**Severity:** P2  
**Likelihood:** MEDIUM  
**Source:** Architecture audit

Each package has its own unit tests against golden fixtures. No test runs `price_trace → adjudicate → detect` as a connected pipeline on a fixture and validates the combined output.

**Mitigation:** Add a thin integration test: `load_trace(fixture) → price_trace → adjudicate → detect → assert(findings match manifest.target_detector)`.

---

### R9 — `PARTIALLY_RESOLVED` verdict never emitted

**Severity:** P3  
**Likelihood:** LOW  
**Source:** GAP-11 (gap analysis)

6 fixtures expect `PARTIALLY_RESOLVED`, but `adjudicate()` never returns it — these fixtures get `RESOLVED (informational)`. The manifest's `expected_verdict` for these fixtures must be what `adjudicate` actually returns, not the PRD's ideal label.

**Mitigation:** Either implement `PARTIALLY_RESOLVED` (requires scenario registry for partial slot completion), or update the manifest to match actual behavior and document the limitation.

---

### R10 — Bootstrap CI is correct but slow

**Severity:** P3  
**Likelihood:** MEDIUM (at scale)  
**Source:** CR-11 (code review)

Python-loop bootstrap over 10,000 resamples is ~300ms per call. Aggregating 6 variants × 250 traces × multiple findings classes → noticeable lag.

**Mitigation:** Vectorize with `rng.choice(arr, size=(n_resamples, n))`.

---

## Risk Matrix

| Risk | Severity | Likelihood | Fix Effort | Blocks |
|------|----------|-----------|------------|--------|
| R1 Inflatable waste | P0 | HIGH | Low (3 localized fixes) | Demo credibility |
| R2 Fabricated numbers | P1 | CERTAIN | High (replay engine) | VC scrutiny |
| R3 D8 over-report | P1 | CERTAIN | Medium (Gate G1) | Production trust |
| R4 D9 weak headline | P1 | HIGH | Medium (classifier) | Commercial pitch |
| R5 Uncalibrated baselines | P2 | HIGH | Medium (corpus) | D4 accuracy |
| R6 Pricing invariant | P2 | LOW | Low | Edge-case correctness |
| R7 CWD rates loading | P2 | MEDIUM | Low | Deployment |
| R8 No integration test | P2 | MEDIUM | Low | Regression safety |
| R9 PARTIALLY_RESOLVED | P3 | LOW | Medium | Verdict completeness |
| R10 Bootstrap speed | P3 | MEDIUM | Low | Scale performance |

---

## Recommended Priority Order

1. **R1** — Fix the three inflation bugs (CR-01, CR-04, CR-08). 30 minutes of code changes. Highest ROI.
2. **R2** — Build the replay engine. Days of work, but it's the product's core differentiator.
3. **R6** — Add pricing invariant assertion + edge case fixes. 20 minutes.
4. **R7** — Inject rates as parameter. 15 minutes.
5. **R8** — Add integration test. 30 minutes.
6. **R3/R4** — Gate G1 and escalation classifier. These are Wave-2 scope and should be prioritized there.
