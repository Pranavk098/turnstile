# Day 2 PRD — Real-provider data + breadth

**Inherits `00-charter.md` in full.** Executor: OpenCode · Reviewer: Claude · Depends on:
Day-1 (live surface) · Feeds: Day-6 (ingest guide), Day-7 (credibility).

## Objective
Make "run it on your own calls" literally true and multi-provider: a **second real
provider adapter (Retell)** plus **one real / real-shaped dataset** ingested and surfaced
live with honest provenance.

## Connection (charter §5)
Consumes the Day-1 service and the frozen `IngestCall` contract + `decision_kind` honesty
boundary (charter §4). The real-data view surfaces on Day-1's live URL. Day-7 launch
leans on this to retire the "all synthetic" objection.

## Day-specific strict rules (add to charter §1)
- MUST NOT fabricate real data. A hand-authored, schema-conformant sample MUST be
  labeled synthetic; only a genuine export may be labeled real.
- The **`decision_kind` honesty boundary MUST hold for every new provider**: inferred
  labels flagged in provenance, never feeding a measured D1 or the margin headline.
- The Retell adapter MUST reuse the existing `provider_info` plumbing (provider-agnostic
  by construction), not a parallel path.
- Real-data acquisition MAY require the flagged small spend / a real account — it MUST be
  opt-in and MUST NOT run in CI.

## Priority factors
### P0 — base case (MUST)
1. `turnstile_ingest.providers.retell` — `from_retell()` / `from_retell_export()` mapping
   the documented Retell call schema → `IngestCall`, with a cited mapping table.
2. CLI `--provider retell`; loud `IngestError` naming the source field on unmappable input.
3. One real **or** clearly-labeled real-shaped dataset ingested end-to-end and **surfaced
   on the live demo** with source + tier provenance.
4. Tests: golden Retell fixture → expected `IngestCall`; unmapped enum → error; acoustic
   absence → D6/D7/D8 ABSENT; inferred `decision_kind` → not counted as measured D1.

### P1 — build-on-top (SHOULD)
5. A provider-agnostic adapter interface (so provider #3 is a drop-in).
6. IF the real data contains a **forwarded call with a failed transfer**, build the
   **D9 tier-2 forwarded-call rule** (deferred until real data — now unblocked).

### P2 — stretch (MAY)
7. A bounded, $0 "drag-drop your export" control on the live UI (size/count-capped).

## Latency budget (charter §2, tightened)
- Ingesting a ≤50-call export → `data.json` MUST complete **< 2 s**.
- The live real-data view MUST meet the Day-1 first-paint budget (< 5 s cold).
- `POST /api/evaluate` on a real single call MUST meet the < 300 ms warm budget.

## Interfaces
`from_retell(call_obj) -> IngestCall`, `from_retell_export(obj) -> list[IngestCall]`;
CLI `--provider {turnstile,vapi,retell}`; a committed `retell-export.sample.json`
(labeled per its true origin). Reuse `run_calls` unchanged — no new report shape.

## Acceptance criteria (EARS)
- WHEN a Retell export is passed, the adapter SHALL emit schema-valid `IngestCall`(s)
  **or** raise `IngestError` naming the offending field. *(check: run both a good and a
  malformed export)*
- WHERE acoustic char fields are absent, the pipeline SHALL mark D6/D7/D8 **ABSENT**.
  *(check: coverage in the rendered report)*
- IF `decision_kind` is inferred, THEN it SHALL NOT contribute to a measured D1 finding
  or the recoverable-margin headline. *(check: the load-bearing "raw detect fires D1 but
  pipeline reports none" test, extended to Retell)*
- WHEN the real dataset is opened on the live demo, the view SHALL show a source line
  naming the provider and its tier. *(check: DOM read on the live URL)*

## Recursive loop — Day-2 dynamic checks (charter §3)
Run a real (or real-shaped) export **through the live service** end-to-end: verify the
rendered numbers, ABSENT labels, provenance, and (if present) the D9 tier-2 finding; run
the malformed-input path and confirm the loud error surfaces (not a 500). Iterate until
all EARS pass; attach transcript. If a genuine real export is unavailable, report that as
an **environmental blocker** (needs the owner's account) and ship the labeled real-shaped
path, not a fabricated "real" one.

## Risks & mitigations
- Retell schema drift → cite current docs; fixture-drive so drift fails a test.
- Temptation to over-infer `decision_kind` → the boundary test + reviewer check.
- Sample mistaken for real → filename + in-file `sample:true` + provenance say synthetic.

## Out of scope
Live pull from a provider API (needs keys → not $0 in CI). More than two providers (P1+).

## Reviewer gate (Claude)
Retell adapter reuses `provider_info`; the `decision_kind` boundary holds; real vs
synthetic labeled truthfully; live demo shows real-shaped data with provenance; CI green.
