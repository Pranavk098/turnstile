# Brief — Wave-3 Item 5: render the ingested report in the dashboard

**Base:** `wave0-foundation` @ current tip (W3-A + W3-B merged; margin reconciliation
landed). Branch `opencode/w3-item5-wire-ingest`. Reviewed + merged by Claude.

## Goal
Make the dashboard render the **turnstile_ingest** report (real-format call data) — not
just the golden fixtures — so a CTO sees the full margin report on realistic data, with
the acoustic detectors **honestly shown ABSENT** where the input lacks G2 fields. The
plumbing is mostly done: W3-A's pipeline already emits dashboard-shaped output
(`packages/ingest/data/data.json` envelope + `call-<id>.json` details, rows shaped like
`calls.json`), and W3-B's dashboard already reads `sample/manifest.json`
(`ingest.status: awaiting W3-A`, `report_path: null` → an honest "not wired yet" line).
Item 5 connects them.

## Boundaries & discipline (hard)
- Lanes: `packages/dashboard/` + `packages/ingest/` wiring only. **Never touch
  `packages/schema/` or `fixtures/golden/`.** Keep the frozen design language.
- **Honesty is the whole point of this item** — the display must not fake or zero the
  absent acoustic detectors. STOP-and-flag on any ambiguity.
- Green + `ruff check packages/` clean; static/offline/no-network preserved.

## Item 5.1 — wire the ingest report as a selectable source
Populate `manifest.json` so `ingest.status` → available and `report_path` points at the
ingest artifact; the dashboard reads the manifest and renders that report (fleet, call
list → per-call drill-down) exactly as it does the fixture data. Define the mechanism
cleanly (e.g. `build_data.py` copies/points at `packages/ingest/data/`, or the dashboard
fetches the ingest path) — no hardcoded numbers; it reads the artifact. Keep the golden
fixtures available as the other source (a labeled switch is fine, not required).

## Item 5.2 — HONEST acoustic-absence in the UI (load-bearing)
The ingest sample lacks G2 acoustic fields, so its `coverage` marks D6/D7/D8 **absent**.
The dashboard MUST reflect that: those classes show **"absent — no data for this input"**
(the coverage reason), **never a $0 bar or a zero finding.** The waste/findings panels
render only present-class findings; a small coverage strip states which classes had data.
This is the product's honesty thesis on real data — make it visible, not buried.

## Item 5.3 — dataset-labeled margin (per the reconciliation decision)
Every recoverable-margin number the dashboard shows is stamped with **(n, dataset)** —
e.g. "2.69% · over these 7 ingest calls" — and no provenance text cites a different
dataset's number than the one displayed. (See `docs/DECISIONS.md`: margin is per-dataset,
never a universal claim.)

## Item 5.4 — converge the ingest margin on the canonical gate (folds in review flag #1)
`turnstile_ingest.pipeline._recoverable_margin` reimplements the §8.3 gate with a looser
condition (both-CI-same-sign) than canonical (`ci_upper < 0`). Reuse
`turnstile_experiments.recoverable_margin` (build a one-variant matrix) OR match its exact
gate. Same 2.69% on the sample; removes the third divergent copy of the gate.

## Acceptance
- Dashboard renders the ingest report end-to-end (fleet with dataset-labeled 2.69% margin,
  7-call list, per-call flame graph/findings/verdict).
- **D6/D7/D8 shown ABSENT (with reason), never zeroed** — a test asserts the dashboard's
  ingest data marks 6/7/8 absent and carries no 6/7/8 findings.
- No hardcoded numbers; reads the ingest artifact + manifest.
- Ingest margin uses the canonical gate (5.4).
- Suite green, ruff clean; design language + offline/no-network preserved. If feasible,
  one screenshot of the ingest view on review.
