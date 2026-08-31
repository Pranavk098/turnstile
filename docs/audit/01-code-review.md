# Code Review — Turnstile Profiler

**Auditor:** Antigravity (Claude Opus 4.6)  
**Date:** 2026-08-31  
**Scope:** All 6 implemented packages (`schema`, `pricing`, `detectors`, `verdict`, `otel`, `stats`)  
**Baseline:** commit `f852980` (2026-08-30 23:27)  
**Method:** Line-by-line source review against PRD, design spec, and schema v1.1 amendment  

---

## Severity Legend

| Level | Meaning |
|-------|---------|
| **CRITICAL** | Will produce wrong numbers in the demo or crash at runtime |
| **HIGH** | Silently corrupts waste/cost figures under plausible inputs |
| **MEDIUM** | Spec violation or logic gap that a skeptical CTO will probe |
| **LOW** | Quality/performance issue; no wrong numbers |

---

## CRITICAL

### CR-01 · D7 Cartesian product over-reports barge-in waste

**File:** [`d07_barge_in.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/d07_barge_in.py#L32-L34)  
**Lines:** 32–34

```python
for tts in turn.tts:
    for playback in turn.playback:
        wasted_chars = tts.chars_synthesized - playback.chars_played
```

**Problem:** Nested `for tts … for playback` is a Cartesian product. A turn with 2 TTS spans × 2 playback spans produces 4 findings, cross-matching unrelated pairs. Waste and LLM attribution are multiplied per pair.

**Why it matters:** Multi-span barge-in turns (fixture `12_multi_waste_b`) will inflate D7 waste figures. In the demo's fleet view, this directly corrupts the Recoverable Margin % headline — the number a VC will divide by revenue.

**Fix:** `zip(turn.tts, turn.playback)` or match by sequence index. Golden fixtures currently have 1:1 TTS-to-playback per turn, which is why tests pass — the bug is latent until replay or live-agent traces with multiple utterances per turn.

---

### CR-02 · Gate G1 structurally unresolved in recorder

**File:** [`recorder.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/otel/src/turnstile_otel/recorder.py#L191-L198)  
**Lines:** 191–198 (`_advance`), 100–184 (`TurnRecorder`)

**Problem:** `_advance` uses a monotonic cursor that forces contiguous, non-overlapping spans. The recorder cannot emit TTS-during-LLM or cross-turn overlap.

**Why it matters:** Acknowledged in `GATES.md` G1. D8 (silence tax) will systematically over-report on live traffic because `union == sum` on every recorder-emitted trace. This is not a code bug — it is a known architectural debt — but it IS the #1 blocker for trusting production numbers. The live agent must not build against this API.

**Fix:** Turns become objects with independent `start()`/`end()` lifecycle. Spans acquire their own `start_offset_ms` from the clock, not from a cursor.

---

## HIGH

### CR-03 · D7 ZeroDivisionError on empty TTS

**File:** [`d07_barge_in.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/d07_barge_in.py#L37)  
**Line:** 37

```python
wasted_fraction = wasted_chars / tts.chars_synthesized
```

**Problem:** `tts.chars_synthesized == 0` → `ZeroDivisionError`. Schema does not enforce `chars_synthesized > 0`.

**Fix:** Add `if tts.chars_synthesized == 0: continue` before the division.

---

### CR-04 · Gate G2 fallback inflates D7 via `len(text)`

**File:** [`recorder.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/otel/src/turnstile_otel/recorder.py#L410)  
**Line:** 410

```python
chars = chars_synthesized if chars_synthesized is not None else len(text)
```

**Problem:** When `chars_synthesized` is omitted, `len(text)` is used — this is `intended`, not `generated`. Gate G2 explicitly forbids this because counting never-synthesized characters inflates D7 in exactly the direction a skeptic attacks.

**Fix:** Remove the fallback. Require explicit `chars_synthesized` or raise. The caller must report billed characters, not intended text length.

---

### CR-05 · Telephony cost silently dropped on zero-duration turns

**File:** [`pricing.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/pricing/src/turnstile_pricing/pricing.py#L111-L115)  
**Lines:** 111–115

```python
total_wall_ms = sum(t.wall_end_ms - t.wall_start_ms for t in trace.turns)
if total_wall_ms > 0:
    for i, turn in enumerate(trace.turns):
        wall_ms = turn.wall_end_ms - turn.wall_start_ms
        turn_costs[i] += tel_cost * (wall_ms / total_wall_ms)
```

**Problem:** If all turns have `wall_end_ms == wall_start_ms` (zero-duration), `total_wall_ms == 0`, the `if` branch is skipped, and telephony cost is never added to `turn_costs`. Since `conv_cost = sum(turn_costs)`, the telephony cost vanishes from the conversation total.

**Why it matters:** `conv_cost` will be wrong. The stage decomposition invariant `Σ span_costs + telephony = conv_cost` breaks silently. This makes CPRC_loaded incorrect.

**Fix:** `elif len(trace.turns) > 0: turn_costs[0] += tel_cost` — distribute evenly or dump into the first turn when pro-rata is impossible.

---

### CR-06 · D3 silently drops finding when turn has no LLM span

**File:** [`d03_redundant_retrieval.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/d03_redundant_retrieval.py#L79-L82)  
**Lines:** 79–82

```python
turn_llm = turn.llm[0] if turn.llm else None
rate_in = rates.llm[llm_key(turn_llm)].input if turn_llm is not None else None
if rate_in is None:
    continue  # no llm.decide in this turn
```

**Problem:** A retrieval turn with no `llm.decide` span skips the finding entirely. The tool's own `cost_usd` is still wasted money — the redundant retrieval happened regardless of whether the turn has an LLM span.

**Fix:** Report `waste = tool.cost_usd` when `rate_in is None`, rather than skipping.

---

## MEDIUM

### CR-07 · Verdict skips FALSE_RESOLVE check for failed handoffs

**File:** [`adjudicate.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/verdict/src/turnstile_verdict/adjudicate.py#L208-L210)  
**Lines:** 208–210

```python
if t_tool.tool_kind is ToolKind.handoff:
    return _adjudicate_handoff(t_turn, t_tool)
```

**Problem:** If the terminal tool is a handoff, the code immediately routes to `_adjudicate_handoff`, bypassing the completion-assertion check in `_adjudicate_mutation`. A rejected handoff where the agent says "I've transferred you successfully" is textbook `FALSE_RESOLVE`, but currently gets labeled `UNRESOLVED`.

**Why it matters:** Under-counting FALSE_RESOLVE weakens the commercial case — FALSE_RESOLVE is "the most expensive failure" per the PRD.

**Fix:** Apply `_asserts_completion` check to handoff branches too, before falling back to `UNRESOLVED`.

---

### CR-08 · D10 double-counts turn cost for same-turn duplicates

**File:** [`d10_tool_thrash.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/d10_tool_thrash.py#L32-L38)  
**Lines:** 32–38

```python
turn_cost = trace.turn_costs[i]
findings.append(Finding(..., waste_usd=turn_cost + tool.cost_usd, ...))
```

**Problem:** If 2 duplicate tool calls occur in the same turn, each finding adds the full `turn_cost`. The turn existed once, not twice — this double-counts the turn cost.

**Fix:** Track turns already attributed. Only add `turn_cost` for the first duplicate in a given turn; subsequent duplicates in the same turn contribute only `tool.cost_usd`.

---

### CR-09 · D5 blind to multi-slot reprompt loops

**File:** [`d05_reprompt_loop.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/d05_reprompt_loop.py#L44-L48)  
**Lines:** 44–48

```python
def slot_fill_choice(turn):
    for span in turn.llm:
        if span.decision_kind is DecisionKind.slot_fill:
            return span
    return None
```

**Problem:** Returns only the first `slot_fill` span. If a turn has multiple `slot_fill` decisions for different slots, reprompt loops on non-first slots are invisible.

**Why it matters:** In a real contact center, agents often collect multiple slots per turn (name + DOB). Loops on the second slot go undetected.

**Fix:** Check all `slot_fill` decisions, not just the first.

---

### CR-10 · `conv_cost` excludes telephony on zero-turn traces

**File:** [`pricing.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/pricing/src/turnstile_pricing/pricing.py#L117-L123)  
**Lines:** 117–123

**Problem:** If a trace has a telephony leg but `turns == []` (caller hung up in queue), `turn_costs` is empty, `conv_cost = sum([]) == 0`. The telephony cost is in `stage_costs["telephony"]` but never reaches `conv_cost`.

**Fix:** `conv_cost = sum(turn_costs) + stage_costs["telephony"]` when no turns exist.

---

## LOW

### CR-11 · Bootstrap loop is 10–20× slower than necessary

**File:** [`stats.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/stats/src/turnstile_stats/stats.py#L68-L71)  
**Lines:** 68–71

```python
for i in range(n_resamples):
    means[i] = rng.choice(arr, size=arr.size, replace=True).mean()
```

**Problem:** Python `for` loop over 10,000 resamples. Vectorizable to `samples = rng.choice(arr, size=(n_resamples, arr.size)); means = samples.mean(axis=1)`.

**Impact:** ~300–500ms per call → ~20ms. Not wrong, but will lag when aggregating across 250+ experiments.

---

### CR-12 · D8 cursor can go backwards on malformed spans

**File:** [`d08_silence_tax.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/d08_silence_tax.py#L123-L124)  
**Lines:** 123–124

```python
if end > cursor:
    cursor = end
```

**Problem:** If `duration_ms < 0` (malformed telemetry), `end < start`, and `cursor` doesn't advance — but the span was still "active" from the union perspective. Unlikely on golden fixtures, possible on live data.

**Fix:** `cursor = max(cursor, end)` — defensive, no behavioral change on valid data.

---

### CR-13 · `Finding.span_id` forced to `str` for turn-level detectors

**File:** [`contracts.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/schema/src/turnstile_schema/contracts.py#L38)  
**Line:** 38

**Problem:** D4 (turn inflation) and D8 (silence tax trailing gaps) synthesize fake span IDs like `"turn3:inflation"` because `span_id: str` is required. These IDs have no referent in the trace — they are fabricated to satisfy the type, breaking referential integrity.

**Fix:** Consider `span_id: str | None = None`. This is a schema-level decision with downstream impact, so it requires owner approval.

---

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 2 | Must fix before demo |
| HIGH | 4 | Must fix before GTM |
| MEDIUM | 4 | Should fix |
| LOW | 3 | Nice to have |
| **Total** | **13** | |

All 400+ tests pass because the golden fixtures avoid the edge cases these bugs trigger (1:1 TTS/playback, non-zero durations, non-empty turns). The test suite validates fixture correctness, not production robustness.
