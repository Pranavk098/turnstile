# Turnstile Wave 0.5 — Schema v1.1 Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Apply the owner-approved schema v1.1 amendment — split ToolCall transport from effect (with a `tool_kind` validator), add absolute `start_offset_ms`/`duration_ms` to every span, regenerate all fixtures with real timelines plus three new effect-driven fixtures, and update the PRD — so Wave 1's detectors and verdict layer build against the corrected contract.

**Architecture:** Two coupled changes to `packages/schema/` and `fixtures/golden/`, then documentation. The schema fields are load-bearing (required), so the fixtures must be regenerated in the same task to keep `contract-test` green.

**Tech Stack:** Python 3.12 · uv · Pydantic v2 (incl. `model_validator`) · PyYAML · pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-turnstile-schema-v1.1-amendment.md` (the authoritative contract for this change; read it — it carries the exact enums, validator rules, D8 formula, and fixture list). Layers on `turnstile-prd.md` and `docs/superpowers/specs/2026-08-30-turnstile-design.md`.

## Global Constraints

- The amendment spec is authoritative for every enum value, validator rule, formula, and fixture. Copy values from it verbatim.
- `turnstile.schema_version` default becomes `"1.1"`.
- Fields added to the base `Span` (`start_offset_ms`, `duration_ms`) are **required ints** (every span carries a real timeline). Fields added to `ToolCall` (`tool_status`, `effect`) have defaults (`ok`, `none`) but are constrained by the validator.
- Validator rule (Pydantic `model_validator(mode="after")` on `ToolCall`): `tool_kind ∈ {mutation, handoff} → effect ∈ {committed,pending,rejected,unknown}`; `tool_kind ∈ {lookup,retrieval} → effect = none`; `tool_status = error → effect ∈ {rejected,none,unknown}`.
- Canonical test command: `uv run pytest packages/schema -q`. Every task ends green + committed. TDD.
- Do not weaken existing v1.0 tests; extend them.

---

## Task 1: Schema v1.1 + fixture regeneration (one green landing)

**Files:**
- Modify: `packages/schema/src/turnstile_schema/enums.py` (add `ToolStatus`, `Effect`)
- Modify: `packages/schema/src/turnstile_schema/spans.py` (base `Span` gains `start_offset_ms`/`duration_ms`; `ToolCall` gains `tool_status`/`effect` + `model_validator`)
- Modify: `packages/schema/src/turnstile_schema/trace.py` (`Conversation.schema_version` default → `"1.1"`)
- Modify: `packages/schema/src/turnstile_schema/__init__.py` (export `ToolStatus`, `Effect`)
- Modify: `packages/schema/tests/test_spans.py`, `test_enums.py` (extend)
- Modify: all `fixtures/golden/*.json` (add offsets/durations to every span; set effects; fixture 17 → `effect=rejected`; escalation 09/14/15 → `handoff.effect=committed`)
- Create: `fixtures/golden/20_unknown_mutation.json`, `21_handoff_rejected.json`, `22_handoff_pending.json`
- Modify: `fixtures/golden/manifest.yaml` (add the 3 fixtures with `effect_edge` category; add `expected_verdict` per fixture)
- Modify: `fixtures/golden/_builder.py` and the authoring scripts (support offsets/durations, tool_status/effect)
- Modify: `packages/schema/tests/test_fixtures.py` (`REQUIRED_DISTRIBUTION` 20→23 with `effect_edge: 3`; add validator-rejection test; add D8 residual-vs-union invariant test)

**Interfaces:**
- Consumes: existing schema package.
- Produces: `ToolStatus(ok|error)`, `Effect(committed|pending|rejected|none|unknown)`; `Span.start_offset_ms:int`, `Span.duration_ms:int`; `ToolCall.tool_status`, `ToolCall.effect` + validator; 23 v1.1 fixtures; updated contract-test.

- [ ] **Step 1 — Write failing tests first (RED):** in `test_enums.py`/`test_spans.py`, assert `ToolStatus`/`Effect` vocabularies; assert `Span` requires `start_offset_ms`/`duration_ms`; assert `ToolCall` accepts `turnstile.tool_status`/`turnstile.effect` via alias; assert the validator REJECTS `tool_kind=mutation` with `effect=none`, `tool_kind=lookup` with `effect=committed`, `tool_kind=handoff` with `effect=none`, and `tool_status=error` with `effect=committed`; assert it ACCEPTS `mutation`+`committed`, `handoff`+`rejected`, `lookup`+`none`. Run `uv run pytest packages/schema/tests/test_spans.py -q` → expect failures.

- [ ] **Step 2 — Enums:** add to `enums.py`:
```python
class ToolStatus(str, Enum):
    ok = "ok"
    error = "error"

class Effect(str, Enum):
    committed = "committed"
    pending = "pending"
    rejected = "rejected"
    none = "none"
    unknown = "unknown"
```

- [ ] **Step 3 — Span base fields:** add required fields to `Span`:
```python
    start_offset_ms: int = Field(alias="turnstile.start_offset_ms")
    duration_ms: int = Field(alias="turnstile.duration_ms")
```
(`VadSegment` inherits them; keep its `extra="allow"`.)

- [ ] **Step 4 — ToolCall fields + validator:** add `tool_status`/`effect` and the `model_validator`:
```python
    tool_status: ToolStatus = Field(ToolStatus.ok, alias="turnstile.tool_status")
    effect: Effect = Field(Effect.none, alias="turnstile.effect")

    @model_validator(mode="after")
    def _check_effect(self):
        mutating = {ToolKind.mutation, ToolKind.handoff}
        if self.tool_kind in mutating and self.effect not in {
                Effect.committed, Effect.pending, Effect.rejected, Effect.unknown}:
            raise ValueError(f"{self.tool_kind} requires a mutating effect, got {self.effect}")
        if self.tool_kind in {ToolKind.lookup, ToolKind.retrieval} and self.effect is not Effect.none:
            raise ValueError(f"{self.tool_kind} must have effect=none, got {self.effect}")
        if self.tool_status is ToolStatus.error and self.effect not in {
                Effect.rejected, Effect.none, Effect.unknown}:
            raise ValueError(f"tool_status=error cannot have effect={self.effect}")
        return self
```
Import `model_validator` from pydantic and `ToolStatus, Effect` from enums.

- [ ] **Step 5 — version + exports:** `Conversation.schema_version` default → `"1.1"`; export `ToolStatus`, `Effect` in `__init__.py` (`__all__` too).

- [ ] **Step 6 — Run schema unit tests (GREEN for models):** `uv run pytest packages/schema/tests/test_spans.py packages/schema/tests/test_enums.py packages/schema/tests/test_trace.py -q` → pass. (test_fixtures still red until fixtures regenerated — next steps.)

- [ ] **Step 7 — Builder support:** extend `_builder.py` so every span helper accepts/sets `start_offset_ms`/`duration_ms`, and `tool()` accepts `tool_status`/`effect`. Timelines are absolute ms from conversation start; `duration_ms` is the span's wall extent (for `audio.playback` truncated by barge-in, the actual played extent).

- [ ] **Step 8 — Regenerate all 20 existing fixtures** with real timelines on every span. Give **at least two** fixtures genuine TTS/LLM overlap with **different overlap shapes** (e.g. one where TTS starts mid-LLM, one where LLM of the next turn starts during playback). Set tool effects: lookups/retrievals `none`; the mutation in fixture 17 → `tool_status=ok, effect=rejected` (agent still asserts "processed"); escalation handoffs in 09/14/15 → `effect=committed`; any other mutation/handoff tools get a sensible committed/etc. Keep every existing detector trigger intact (re-verify 01-15 still trip their detector).

- [ ] **Step 9 — Author the 3 new effect fixtures** (`effect_edge` category): `20_unknown_mutation` (required mutation `effect=unknown` after a timeout `tool_status=error`; expected_verdict ambiguous, confidence-capped); `21_handoff_rejected` (`tool_kind=handoff, effect=rejected`; expected_verdict `UNRESOLVED`); `22_handoff_pending` (`tool_kind=handoff, effect=pending`; expected_verdict not ESCALATED). All schema-valid with full timelines.

- [ ] **Step 10 — Manifest + contract-test:** add the 3 fixtures to `manifest.yaml` under `category: effect_edge`; add an `expected_verdict` key to every fixture entry. In `test_fixtures.py`: set `REQUIRED_DISTRIBUTION` to include `effect_edge: 3` (total 23); add a test that an illegal `effect×tool_kind` combination raises `ValidationError`; add a D8 invariant test asserting, on the non-overlapping fixtures, that residual-silence (`billed_wall − Σ covered`) equals union-gap-silence (`billed_wall − |union of active intervals|`), and that they DIVERGE on the overlap fixtures by exactly the overlap.

- [ ] **Step 11 — Full suite GREEN:** `uv run pytest packages/schema -q` → all pass (23 fixtures valid, distribution 23, validator + invariant tests green). Commit in logical commits (schema; fixtures+contract-test), ending green.

---

## Task 2: PRD v1.1 documentation

**Files:**
- Modify: `turnstile-prd.md` (§3.1/§3.2 span attributes + tool.call fields; §6 Detector 8 union formula + Detector 9 tier 2; §7 verdict `effect` evidence + `unknown` confidence cap + `ESCALATED` requires committed handoff; bump schema_version note to 1.1)

**Interfaces:**
- Consumes: the amendment spec.
- Produces: PRD reflecting v1.1. Documentation only — no code, no tests.

- [ ] **Step 1:** Update PRD §3.1/§3.2: add `turnstile.start_offset_ms`/`turnstile.duration_ms` to the span attribute blocks; add `turnstile.tool_status`/`turnstile.effect` to the `tool.call` block; note `result_hash` demoted to Detector-10-only.
- [ ] **Step 2:** Update PRD §6 Detector 8 row to the union formula (`active_ms = |union of active intervals|`, `silence_ms = billed_wall − active_ms`, attribution by next span). Add Detector 9 tier 2 (spend before a `rejected` handoff).
- [ ] **Step 3:** Update PRD §7: terminal-tool-state evidence reads `effect`; add the `unknown` → confidence≤0.6 / not-RESOLVED-or-FALSE_RESOLVE rule; `ESCALATED` requires `handoff.effect=committed` (rejected → UNRESOLVED). Bump the `turnstile.schema_version` reference to `1.1`.
- [ ] **Step 4:** Commit (docs only).

---

## Self-Review

Spec coverage: T3 tool_status/effect + validator (Task 1 Steps 2,4), handoff-as-mutation (Step 4 validator), unknown/ESCALATED verdict rules (documented Task 2 §7; enforced in Wave 1 verdict layer), T1 offsets + D8 union (Task 1 Steps 3,10; Task 2 §6), expected_verdict manifest metadata (Step 10), 3 new fixtures + distribution 23 (Steps 9-10), two-overlap-shape requirement (Step 8), PRD updates (Task 2). No placeholders; enums/validator/formula values trace to the amendment spec. Type consistency: `ToolStatus`/`Effect`/`start_offset_ms`/`duration_ms`/`tool_status`/`effect` used consistently across steps.
