# PRD 03/04/05 — improvements delegation brief

**Executor:** OpenCode (or Claude, if doing it inline to save budget) · **Reviewer:**
Claude · **Scope:** one do-now follow-up that makes the quality layer *visible* in the
committed demo, plus a documented deferred list.

## Global constraints (unchanged)

- **$0**, no paid call anywhere; engine purity (no eval math in the dashboard/service).
- **Additive only:** cost / verdict / findings / recoverable-margin numbers must stay
  byte-identical; the only new thing on the wire is the `quality` block.
- No frozen-contract edits; `uv run pytest` green, no regression.

---

## Task — surface quality beside cost in the committed demo (04/05 follow-up)

**Why:** PRD 04 wired `evaluate_quality` into the **ingest** pipeline, and PRD 05 added
a Quality column + rubric to the **live-eval panel** (`renderEvalReport`). But the demo's
first screen — the committed fleet of 23 golden fixtures and their drill-downs — shows no
quality, for two concrete reasons:
1. `packages/dashboard/build_data.py` builds the golden-fixture data with its own
   `price_trace → adjudicate → detect` calls (≈ lines 101–110, 141) and **never calls
   `evaluate_quality`**, so the committed `call-*.json` / fleet carry no `quality` key.
2. The committed fleet/report table (the main dashboard table, **distinct from**
   `renderEvalReport`'s eval-panel table) has **no Quality column**; only the live-eval
   panel does.

So a visitor who just opens the demo URL never sees the pivot ("quality beside cost")
until they paste their own call. This task fixes that.

**Do:**
1. **`build_data.py`:** compute `evaluate_quality(priced, verdict)` for each golden
   fixture and emit its JSON `quality` block into the per-call detail files (and,
   if the fleet rows carry an overall, the fleet overall) — **additively**, next to the
   existing verdict/findings. Do not change any existing number. Keep the file's
   "writes data only, never HTML" contract (its tests assert no `.html` changes).
2. **`index.html` committed fleet/report table:** add a **Quality column** that reads
   `call.quality` (overall label + `qualityTierChip(tier)`) from the committed data, and
   ensure the committed drill-down renders the rubric via the **existing**
   `renderQualityRubric` (single definition — do not fork it; the front-end test already
   pins one definition). Archived/absent quality still reads "not computed", never zeros;
   pending judge dims still read "calibration pending", never numerals.
3. **Regenerate committed data:** run `uv run python packages/dashboard/build_data.py`
   (and the ingest data regen, `python -m turnstile_ingest --sample`, if its committed
   `data.json` should also carry quality) and commit the resulting `sample/*.json` /
   `data/` changes.

**Acceptance (guardrails matter most):**
- The committed fleet view shows a **Quality** cell (label + tier chip) for the golden
  calls, and a drill-down shows the full rubric — reusing the existing renderer.
- **Number-stability proof:** every pre-existing headline value (recoverable margin,
  CPRCs, per-class findings counts, D7 %, conditional totals) is **byte-identical**
  before/after — the diff adds only `quality` blocks. `test_home`, `test_build_data`,
  and the dashboard/service suites stay green. If any pre-existing number moves, **stop
  and report** — that means an unintended change, not a quality addition.
- The quality overall on the golden fixtures reads `measured` tier (deterministic dims),
  consistent with the verdict; pending judge dims never appear as scores.
- Full suite green; `$0`; no frozen-contract edits.

---

## Explicitly deferred (do NOT build now; documented triggers)

- **[04] Barge-in courtesy → measured.** Needs real playback/audio spans; unmeasured on
  synthetic by design. Trigger: wiring the live-agent's real Piper playback into ingest.
- **[04] Faithfulness / answer-relevance judge implementations.** Blocked on the 60-label
  calibration study (κ ≥ 0.75, ECE) — explicitly out of PRD 04 scope. Trigger: a
  calibration dataset exists. The gate is already built and proven; only the judge is
  missing, and it must stay missing until calibrated.
- **[03] Cache/job observability** (hit-rate, metrics endpoints). Trigger: an actual perf
  question the current tests can't answer.
- **[03] Real *paid* variant sweep via `/api/experiments`.** That is the paid-preservation
  roadmap — it costs money and violates the $0 demo. Keep MockBackend-only here.
- **[05] React/Solid rewrite.** Owner chose vanilla; revisit only if the console outgrows
  it.

## Handoff

- Small enough to do inline without OpenCode if budget is tight (Claude can implement +
  self-verify the number-stability guard).
- **Reviewer will check:** additive-only (numbers byte-stable), `build_data.py` still
  data-only, renderer reuse (no `renderQualityRubric` fork), pending/absent rendered as
  text not numerals, and the demo actually shows quality beside cost on first screen.
