# Brief — dashboard guided-tour legibility polish

**Base:** `wave0-foundation` @ `66fe8ed`. Branch `opencode/dash-guided-tour`.
Reviewed + merged by Claude. Runs in **parallel** with `opencode/wave2-exp-hardening`
(disjoint files: this touches `packages/dashboard/` only).

## Goal
A first-time viewer who was handed the URL with **no explanation** understands the whole
honest story and can navigate it: what Turnstile is, the three honesty tiers, what each
number means and its dataset, and how to move home → fleet → one call → ingested data.
Today the data is all there; the *legibility* is not. This is **polish, not redesign** —
extend the frozen design language, do not rebuild panels or add product features.

## Boundaries (hard)
- `packages/dashboard/` **only**. NEVER touch `packages/schema/`, `fixtures/golden/`,
  or any pipeline package. Keep the frozen design language (fonts, palette, SVG style).
- Preserve the W3-B invariant: `build_data.py` stays **decoupled** from `index.html`
  (no HTML-writing path in build_data; the existing `test_build_module_has_no_html_writing_path`
  must stay green).
- Static / offline / no-network. Green + `ruff check packages/` clean.

## Items (concrete legibility criteria)
1. **Orientation on `home.html`** — a stranger lands here first. One screen that states,
   in plain language: what Turnstile is (one sentence), the three tiers (Measured /
   Instrumented-not-measured / Modeled-or-not-measured) and how to read them, and a
   clear entry into the report. No jargon walls.
2. **Self-contained "What is this?"** on `index.html` — the explainer answers "what am I
   looking at, and why should I trust these numbers" without external docs. Each tier
   chip (PROVEN / MEASURED / CONDITIONAL) carries a plain-language tooltip.
3. **Every number wears its dataset** — the `(n, dataset)` label is visible on each
   recoverable-margin figure (per the per-dataset rule in `docs/DECISIONS.md`), and the
   dataset switch states plainly what changed when toggled (Golden fixtures ↔ Ingested).
4. **Absence is legible** — D6/D7/D8 "absent — no data for this input" carries a
   hover/explainer making clear absent ≠ zero waste (why the log lacked the acoustic
   fields). A stranger must not read it as "$0 waste."
5. **Navigation affordances** — home → fleet → per-call drill-down → back is obvious
   (visible links/controls, working back-navigation, the call list clearly clickable).
6. **Responsive** — renders correctly under 680px with no horizontal body scroll (wide
   tables/charts scroll inside their own container).

## Acceptance
- A legibility checklist (put it in the delivery report) where each of the six items is
  demonstrably satisfied.
- A test asserting the new legibility hooks exist in `index.html`/`home.html` (the tier
  tooltips, the "what is this" explainer, the dataset-change copy, the absence explainer)
  — same static-assertion style as `test_ingest_wire.py`.
- Design language preserved; `build_data.py` decoupling intact (its test green).
- Suite green, ruff clean. Include a screenshot of `home.html` and one per-call view on
  review.

## Explicitly NOT in scope
No new panels, no new data, no redesign, no framework, no schema/fixtures. If a
legibility fix seems to need pipeline or schema data that isn't already in
`sample/*.json`, STOP and flag — do not invent it in the dashboard.
