# GLM brief — W3-B: explorable product UI

**Base:** `wave0-foundation` @ current tip. Branch `opencode/w3b-ui` (stacked series
OK). Claude reviews + merges. Tasks 1–4 are independent of W3-A; task 5 waits on it.

## Goal
Turn the static single-page report into a **navigable product** a CTO clicks through:
landing page → a call list → drill into one call (its flame graph, findings, verdict,
cost). Plus fix the build/authoring coupling and land the design-audit polish. The
`home.html` landing + design system (embedded fonts, tokens, SVG charts) are a **frozen
baseline to EXTEND, not replace.**

## Boundaries & discipline (hard)
- Lanes: `packages/dashboard/` + any data-gen wiring in `experiments`/`ingest`. **Never
  `packages/schema/` or `fixtures/golden/`.** Keep the current design language.
- Static, offline, no-network stays true (embedded fonts, fetched local JSON).
- Each branch ends green + `ruff check packages/` clean; keyboard-accessible;
  page never scrolls sideways (wide content scrolls inside its own container).

## Item 1 — DECOUPLE `build_data.py` from `index.html` (FIRST — prerequisite, fixes a real bug)
Today `build_data.py` **rewrites `index.html`** (embeds JSON, and its HTML regeneration
**mangles the panel containers** — this already broke the dashboard once). Fix the
architecture: `build_data.py` writes ONLY data (`sample/*.json` / a `data.json`);
`index.html` is hand-authored and **fetches** that data; the build never regenerates or
embeds HTML. Remove the index.html-writing path from `build_data.py`.
**Acceptance:** running `build_data.py` modifies **no** `.html` file (test-asserted);
the dashboard renders purely from fetched JSON; nothing clobbers the panels.

## Item 2 — per-call navigation
Generate per-call data for **all** calls (not just the hero fixture). Add a **call-list
index** (id · scenario · cost · verdict · top waste) → click a call → a **detail view**
for that call: its cost flame graph, findings, verdict, and per-stage cost. Hash-based
client routing (static-friendly), keyboard-accessible, works served and ideally
`file://`.

## Item 3 — finish the landing page
Complete `home.html` as the product entry (what Turnstile is, the honest tiers, a clear
path into the dashboard). Extends the frozen baseline.

## Item 4 — design-audit P0/P1 fixes
- **Contrast:** apply the `--faint: #8a8f98` fix (already in `home.html`) to `index.html`.
- **Narrow render:** verify <680px isn't broken; every table scrolls inside its own
  `overflow-x:auto` container; body never scrolls sideways. (Screenshot or note it.)
- **Numbers:** `font-variant-numeric: tabular-nums` + consistent precision so columns align.
- **`→` arrow affordance:** make it a real interactive control (hover/cursor) or remove it.
- **"no measured effect" rows:** style intentionally muted/italic so they read as
  "checked, it's zero," not missing data.

## Item 5 — render REAL ingested data (after W3-A lands)
Point the dashboard at the report produced by `turnstile_ingest` (Item 5 of W3-A), so
the product shows a full margin report on real-format call data, with the acoustic
detectors honestly labeled absent when the input lacks acoustic fields. Can be the final
step / a follow-up once W3-A merges.

## Acceptance
- `build_data.py` touches no HTML (test-enforced); dashboard renders from fetched JSON.
- Navigable list → per-call detail, keyboard-accessible.
- Design fixes applied; <680 render verified; tabular numbers; arrow + degenerate-row
  styling resolved.
- Suite green, ruff clean; design language preserved.
