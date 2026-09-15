# Day 6 PRD — Docs site + narrative assets

**Inherits `00-charter.md` in full.** Executor: OpenCode · Reviewer: Claude · Depends on:
Days 1–5 · Feeds: Day-7 (launch).

## Objective
A professional **docs site**, a polished README with visual proof, and a **2–4 min demo
video** — the credibility surface a stranger judges the project by in 60 seconds.

## Connection (charter §5)
Documents Days 1–5 and links their outputs: the live URL (Day-1), PyPI install (Day-5),
`PERF.md` numbers (Day-3), the quality/calibration report (Day-4), the ingest guide
(Day-2). Every number shown MUST trace to its source doc (charter §1.4).

## Day-specific strict rules (add to charter §1)
- Docs MUST match reality: every number traces to a source (`METHOD.md`/`PERF.md`/
  calibration report); a doc-number that diverges MUST fail CI (a doc-number guard).
- Every internal link MUST resolve (link-check gate). The **honesty framing MUST be
  foregrounded**, not buried.
- The video and GIF MUST show the *actual live product* (quality beside cost), not a mockup.

## Priority factors
### P0 — base case (MUST)
1. **mkdocs-material** site on **GitHub Pages**: methodology, honesty rule, ingest guide,
   quality-eval guide, auto API reference, the PERF story.
2. **README polish**: a hero **GIF/screenshots** of the live demo (quality beside cost),
   a <10-min quickstart, and the full badge row (PyPI, docs, CI, license, live demo).
3. A **2–4 min demo video** (reuse the PRD demo script, now with quality beside cost).

### P1 — build-on-top (SHOULD)
4. A **doc-number guard** in CI (asserts key figures in docs == their source docs).
5. Docs search; a "quickstart a stranger finishes in < 10 min" (dynamically timed).

### P2 — stretch (MAY)
6. An interactive API playground page hitting the live service. 7. Versioned docs.

## Latency budget (charter §2, tightened)
- Docs site **first paint < 3 s**; Lighthouse performance **≥ 90**.
- Hero GIF **< 5 MB**; README MUST render in < 2 s on GitHub.

## Interfaces
`mkdocs.yml` + `docs/` content; a Pages deploy workflow; the link-check (exists) extended
to the site; a `docs-numbers` CI check; `README.md` assets under `docs/`.

## Acceptance criteria (EARS)
- WHEN a visitor opens the docs site, it SHALL become interactive in **< 3 s** and every
  internal link SHALL resolve. *(check: Lighthouse + link-check against the built site)*
- WHEN the README renders on GitHub, the hero SHALL show quality-beside-cost and the demo
  badge SHALL link to a 200 page. *(check: render + curl the links)*
- IF any documented number diverges from its source doc, THEN CI SHALL fail. *(check: the
  doc-number guard on a seeded mismatch, then clean)*
- WHEN a new user follows the quickstart, they SHALL reach a running result in **< 10 min**.
  *(check: a timed clean-machine dry run)*

## Recursive loop — Day-6 dynamic checks (charter §3)
Build and **serve** the docs (mkdocs serve); run Lighthouse + link-check + the doc-number
guard; click through the live-demo and PyPI links; time the quickstart on a clean
checkout. Iterate until every gate + budget is green. Record the video only after the
live product passes Day-1's budgets (so the demo reflects reality). Attach Lighthouse +
link-check transcripts.

## Risks & mitigations
- Docs drift from reality → the doc-number guard + link-check every loop.
- Heavy/slow docs → Lighthouse gate; compress assets.
- Overclaiming in the narrative → reviewer diff vs METHOD/LIMITATIONS/PERF.

## Out of scope
A marketing site rebuild; a CMS; the React console.

## Reviewer gate (Claude)
Docs site live + < 3 s + links resolve; README hero shows the real product; every number
traces to a source (guard green); video reflects the live budgets; CI green.
