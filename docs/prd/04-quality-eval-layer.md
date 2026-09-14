# PRD 04 — Quality-eval layer (Interpretation B core)

**Owner (spec):** Pranav Koduru · **Executor:** OpenCode · **Reviewer:** Claude
**Status:** ready to build · **Roadmap:** #4 — the actual pivot to "full-stack voice
evals"

---

## 1. Thesis

Turnstile answers *what a call cost* and *whether it resolved*. It does not yet answer
*was it any good* — and that is the umbrella that makes the product legible as an
"evals system." This PRD adds a **quality-eval layer reported beside cost**, so a call
reads as: **"resolved-quality: pass · cost $1.34 · $0.19 recoverable."** Quality is
added *alongside* the cost/margin wedge, never in place of it — the cost layer stays
the differentiator (per the confirmed Interpretation B).

**The crux — and the reason this is a Turnstile feature and not a me-too eval tool —
is honesty.** The repo already refuses to ship its LLM verdict-judge until it is
calibrated (60 hand labels + Cohen's κ ≥ 0.75; `LIMITATIONS.md` §6, PRD §7). The
quality layer inherits that discipline exactly: **deterministic, rule-based quality
dimensions ship first and run in the $0/CI path; any model-graded dimension is a
declared no-op until calibrated, and is labeled `not-measured` until it is.** A quality
score that isn't calibrated is decoration, and decoration is the one thing this repo
does not ship.

## 2. Non-goals

- **Not a general quality-eval framework** competing with Coval/Hamming. A focused,
  voice-aware rubric that pairs with cost.
- **No paid model call in the default or CI path.** Default quality dimensions are
  deterministic over data the trace already carries.
- **No tuning to make scores pass.** Same rule as the corpus: never shaped to flatter.
- **No frozen-contract edits.** Reuses `PricedTrace` + `Verdict`; adds a new report
  section, not a schema change to §3–5.
- Does **not** replace or reweight the verdict layer; it sits beside it.

## 3. Hard constraints

1. **$0 default path.** Deterministic dimensions only, no network, in CI.
2. **Calibration gate (the §5-equivalent crux).** Any dimension that needs an LLM judge:
   - ships as an explicit **no-op returning `not-measured`** until calibration exists,
     mirroring verdict evidence-source 5;
   - when built, requires ≥60 hand labels + reported Cohen's κ and ECE, and κ ≥ 0.75 to
     be allowed to emit a score;
   - is **gated behind the paid flag** (`TURNSTILE_ALLOW_PAID`) and **off by default**;
   - a model-graded score never feeds a headline or the "beside-cost" summary until
     calibrated — exactly as an inferred `decision_kind` never feeds a measured D1.
3. **Honesty tiering on every dimension.** Each quality dimension is labeled
   `measured` (deterministic on real trace data), `instrumented` (mechanism, magnitude
   not claimed), or `not-measured` (calibration pending) — same vocabulary as METHOD.
4. **Determinism** for all default dimensions.

## 4. Design

New package: `packages/quality/` (`turnstile_quality`), one entry point:

```python
def evaluate_quality(priced: PricedTrace, verdict: Verdict) -> QualityReport: ...
# QualityReport = { dimensions: [QualityDimension], overall: {label, tier}, evidence[] }
# QualityDimension = { id, score|None, label, tier: measured|instrumented|not_measured,
#                      evidence: dict, method: "deterministic"|"judge_calibrated"|"judge_pending" }
```

### 4.1 v1 quality dimensions (deterministic, $0, ship first)

Derive each only from data the trace/verdict already carry — no invented signals:

| Dimension | Deterministic rule (illustrative — confirm against schema) | Tier |
|---|---|---|
| **Task success** | agrees with the verdict's terminal-tool evidence (RESOLVED ⇒ required mutation `effect=committed`) | measured |
| **Slot completeness** | required scenario slots filled before resolution (registry-defined) | measured |
| **Escalation appropriateness** | escalation happened iff the escalation signal was present (ties to D9's `turn_of_no_return`) | measured |
| **Barge-in courtesy** (voice-specific) | agent yielded on caller barge-in vs. talked over (from `audio.playback.truncated_by` / turn `barge_in`) | measured where acoustics present, else `instrumented`/absent |
| **Non-repetition** | no reprompt loop / duplicated required prompt (reuses D5/D10 signals) | measured |

These reuse existing detector/verdict evidence, so they are consistent with the rest of
the tool by construction — not a parallel truth.

### 4.2 Optional gated judge dimensions (declared, shipped as pending)

Define (but ship as `judge_pending` no-ops) the dimensions that genuinely need a model:
**faithfulness/grounding** (did the agent's claims match tool results) and **answer
relevance**. Each returns `score=None, tier=not_measured, method="judge_pending"` with a
note pointing at the calibration requirement. They may only start scoring after §3.2.

### 4.3 Reported beside cost

- Wire `evaluate_quality` into `turnstile_ingest.pipeline.run_call`/`_run_priced` so the
  per-call report and the fleet report gain a `quality` block next to the existing
  `verdict`, `conv_cost_usd`, and `findings`.
- The one-line summary the dashboard/console shows pairs them:
  `quality: <overall label/tier> · cost $X · $Y recoverable`.
- Provenance: each dimension's tier + method rides to the wire, unstripped.

## 5. Build phases

- **P0 — package + `QualityReport` types + entry point** (no dimensions yet). *Verify:*
  imports clean, empty report constructs, no frozen-schema touch.
- **P1 — deterministic dimensions (§4.1)** on the golden fixtures. *Verify:* each fires
  correctly on the fixture engineered for it; each carries a tier; task-success agrees
  with the verdict on every golden trace.
- **P2 — judge dimensions declared as pending no-ops (§4.2).** *Verify:* they return
  `not_measured`/`None`; a test asserts they never emit a score without calibration and
  never appear in the beside-cost summary.
- **P3 — wire into the pipeline + reports beside cost (§4.3).** *Verify:* per-call and
  fleet reports carry a `quality` block; the paired one-liner renders; provenance/tier
  present; native numbers (cost/verdict/findings) unchanged.
- **P4 — dashboard/console surfacing** (or hand to PRD 05). *Verify:* quality shows
  next to cost with honest tier badges; deterministic vs pending clearly distinguished.

## 6. Definition of Done (prod-ready)

- [ ] `evaluate_quality` returns a tiered `QualityReport` from `PricedTrace`+`Verdict`,
      deterministic and $0.
- [ ] The v1 deterministic dimensions compute correctly on the golden fixtures and agree
      with existing verdict/detector evidence (no parallel/contradictory truth).
- [ ] Every dimension is labeled measured/instrumented/not-measured; judge dimensions
      ship as calibration-pending no-ops and **cannot** emit a score or reach the
      beside-cost summary until §3.2 is satisfied — **proven by a test**.
- [ ] Reports show quality **beside** cost; cost/verdict/findings numbers are unchanged.
- [ ] No paid call in the default/CI path; any future judge is paid-flag-gated + off by
      default.
- [ ] `uv run pytest` green incl. new `packages/quality/tests`; suite not regressed.
- [ ] METHOD.md/LIMITATIONS.md gain a short "quality layer" section stating exactly what
      is measured vs pending — same honesty framing as the rest of the repo.

## 7. Test requirements

- Per-dimension fixture tests (fires when it should, silent when it shouldn't).
- Consistency test: task-success never contradicts the verdict's terminal-tool label.
- **Calibration-gate test (load-bearing):** a judge dimension with no calibration returns
  `not_measured` and is absent from the beside-cost summary; assert it cannot be coaxed
  to emit a score. (The §2-equivalent of PRD 02's "D1 never reports inferred spans.")
- Provenance/tier retention through pipeline → report.

## 8. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| Shipping an uncalibrated model judge as if measured | **High** | §3.2 gate + load-bearing test; reviewer checks this first |
| Quality contradicts the verdict (two truths) | High | Deterministic dimensions derive from the same evidence; consistency test |
| Scope creep into a full eval framework | Med | v1 rubric is fixed and small; §2 non-goals |
| A dimension needs data the trace lacks | Med | Then it is `instrumented`/absent, never faked (reuse the acoustic-absence pattern) |

## 9. Out of scope / future

- Model-graded dimensions actually scoring (needs the 60-label calibration set first).
- Quality-vs-cost Pareto/tradeoff analytics (a later analysis feature).
- Per-scenario custom rubrics.

## 10. Handoff / dependencies

- Independent of PRD 03; feeds PRD 05 (the console renders quality beside cost).
- **Reviewer will check, in order:** the calibration gate (no uncalibrated score ever
  reaches a headline or the beside-cost line), dimension/verdict consistency, honesty
  tiering to the wire, deterministic $0 default, and no frozen-contract edits.
