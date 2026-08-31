# Architecture Audit — Turnstile Profiler

**Auditor:** Antigravity (Claude Opus 4.6)  
**Date:** 2026-08-31  
**Scope:** Pipeline architecture, package boundaries, data flow, contract integrity  

---

## Architecture Overview

```
Layer 0   agent/        (NOT BUILT)    Live Pipecat pipeline → produces OTel spans
Layer 1   otel/         (PARTIAL)      TraceRecorder → Trace model (schema-validated)
Layer 2   pricing/      (COMPLETE)     price_trace(Trace, RateTable) → PricedTrace
Layer 3   detectors/    (COMPLETE)     detect(PricedTrace, Verdict, Baselines) → [Finding]
Layer 4   verdict/      (COMPLETE)     adjudicate(PricedTrace) → Verdict
Layer 5   replay/       (NOT BUILT)    replay(Trace, VariantSpec, from_turn) → Trial
Layer 6   dashboard/    (COMPLETE)     Static HTML consuming pre-computed JSON

Support:
  schema/     Pydantic v2 models + loaders (frozen v1.1)
  stats/      Wilson interval, bootstrap CI, experiment aggregation
  fixtures/   23 golden traces + manifest
```

---

## Architectural Strengths

### S1 — Clean data-down dependency graph

```
schema (leaf)
  ↑ pricing (schema)
  ↑ verdict (schema)
  ↑ detectors (schema + rates.yaml directly)
  ↑ stats (schema)
  ↑ otel (schema + opentelemetry-sdk)
```

No circular dependencies. `pricing` and `verdict` are completely independent — pricing never reads verdict, verdict never reads costs. Detectors depend on both via `PricedTrace` + `Verdict` but never import from pricing internals (rate-key resolution is deliberately re-derived in `_rates.py`). This is correct and deliberate.

### S2 — Frozen contracts + golden fixtures as decoupling interface

The 23 golden fixtures + `manifest.yaml` serve as an integration test contract that lets packages develop independently. Every package's test suite validates against these fixtures. This is the right pattern for a 48-hour build with parallel agents.

### S3 — Schema validation as the trust boundary

Pydantic `extra="forbid"` + `model_validator` on `ToolCall` (effect × kind × status) means malformed data fails at parse time, not at detector time. The `ToolCall._check_effect` validator (spans.py L62–73) is the most important 11 lines in the codebase — it prevents the entire class of "agent claims committed but schema says impossible" data quality issues.

---

## Architectural Concerns

### A1 — Circular data flow: verdict before detectors, but D9 needs verdict

**Impact:** MEDIUM

`detect()` signature: `detect(trace: PricedTrace, verdict: Verdict, baselines: Baselines) → list[Finding]`

Detector 9 (escalation debt) reads `verdict.label` and `verdict.turn_of_no_return`. This creates an implicit ordering constraint: verdict MUST run before detectors. If a future refactor attempts to pipeline them in parallel, D9 breaks silently.

This isn't wrong, but it means the pipeline is `price → adjudicate → detect`, not `price → {adjudicate, detect}`. The dependency should be documented in an explicit pipeline orchestrator (which doesn't exist yet).

### A2 — Detectors load rates.yaml via CWD-relative path

**Impact:** MEDIUM

[`_rates.py`](file:///c:/Users/prana/OneDrive/Desktop/Turnstile/packages/detectors/src/turnstile_detectors/_rates.py#L23) line 23:

```python
RATES_PATH = "pricing/rates.yaml"
```

Resolved relative to `os.getcwd()`, not to the package or repo root. Works because `uv run pytest` always runs from the repo root. Breaks if:
- Detectors are imported by code running from a different directory
- Deployed behind a web server with a different CWD
- Called from a notebook, script, or REPL

For a GTM product, `rates.yaml` should be loaded via a parameter to `detect()`, the same way `price_trace()` accepts a `RateTable`, not hardcoded via CWD.

### A3 — No pipeline orchestrator

**Impact:** MEDIUM

The full pipeline (`load_trace → load_rates → price_trace → adjudicate → detect → aggregate`) has no single entry point. Each step is called manually. For a demo this is fine. For a GTM product:
- The ordering constraint (A1) is enforced by convention, not code
- Error handling between stages is the caller's problem
- There's no place to inject logging, timing, or telemetry

Recommendation: a thin `turnstile.run(trace_path, rates_path, baselines_path) → FullReport` orchestrator.

### A4 — Dashboard is fully disconnected from the pipeline

**Impact:** LOW

The dashboard (`packages/dashboard/index.html`) consumes `sample/*.json` — hand-authored JSON that does NOT come from the actual pipeline. For the demo this is fine (the numbers are memorized). For GTM, the pipeline must produce the exact JSON the dashboard expects, and no such serializer exists yet.

### A5 — OTel recorder produces `Trace` but pipeline consumes `PricedTrace`

**Impact:** LOW (informational)

The recorder outputs a `Trace`. The pipeline entry point is `price_trace(Trace, RateTable) → PricedTrace`. This gap is correctly bridged by calling `price_trace` on the recorder's output. Just noting that no integration code exists to do this — the recorder and the analysis pipeline are not wired together yet. This is expected (the live agent doesn't exist), but should be the first thing built during Wave 2.

---

## Package Boundary Assessment

| Boundary | Correct? | Notes |
|----------|----------|-------|
| schema → pricing | ✅ | `price_trace` accepts `Trace` + `RateTable`, returns `PricedTrace` |
| schema → verdict | ✅ | `adjudicate` accepts `PricedTrace`, returns `Verdict` |
| schema → detectors | ✅ | `detect` accepts `PricedTrace` + `Verdict` + `Baselines`, returns `[Finding]` |
| schema → stats | ✅ | `aggregate_experiment` accepts `[Trial]`, returns `ExperimentResult` |
| schema → otel | ✅ | `TraceRecorder.finalize()` returns `Trace` |
| pricing ↔ detectors | ✅ | Detectors re-derive rate-key resolution independently (`_rates.py`) — correct decoupling |
| verdict ↔ detectors | ⚠️ | D9 reads `verdict.label` — one-way dependency, correct but creates ordering constraint (A1) |
| pricing ↔ verdict | ✅ | No dependency |

---

## Contract Integrity

| Contract | Defined in | Producers | Consumers | Status |
|----------|-----------|-----------|-----------|--------|
| `Trace` | schema | otel, fixtures | pricing, verdict, detectors | ✅ Frozen v1.1 |
| `PricedTrace` | schema | pricing | verdict, detectors | ✅ Clean |
| `Finding` | schema | detectors | replay (future), dashboard | ✅ Clean |
| `Verdict` | schema | verdict | detectors (D9) | ✅ Clean |
| `Trial` | schema | replay (future) | stats | ✅ Schema defined, no producer yet |
| `ExperimentResult` | schema | stats | dashboard | ✅ Schema defined |
| `RateTable` | schema | rates.yaml loader | pricing, detectors | ✅ Frozen |
| `Baselines` | schema | fixtures/sample/ | detectors (D4, D9) | ⚠️ Sample only; no calibrated production baselines |

---

## Verdict

The architecture is sound for a 48-hour prototype. The dependency graph is clean, contracts are frozen, and the golden-fixture decoupling pattern is the right call for parallel development.

**Three things to fix before GTM:**
1. **Pipeline orchestrator** — wrap the `price → adjudicate → detect` ordering in a single callable
2. **Rates injection** — remove CWD-relative loading from detectors; pass `RateTable` as a parameter
3. **Dashboard wiring** — build the serializer that connects pipeline output to dashboard JSON
