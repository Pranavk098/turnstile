# PRD 05 — Eval console front-end (full-stack surface)

**Owner (spec):** Pranav Koduru · **Executor:** OpenCode · **Reviewer:** Claude
**Status:** ready to build (after 03 + 04) · **Roadmap:** the "full-stack" surface

---

## 1. Thesis

PRDs 03 and 04 add fast async eval runs and a quality layer, but a visitor still can't
*drive* an eval end-to-end and see quality + cost together, or compare two runs. This
PRD adds an **eval console**: submit a call or a small dataset, watch the eval run,
read **quality beside cost**, open the flame graph + rubric, and **compare two runs or
a baseline-vs-cheaper-variant sweep** — the concrete artifact that makes "full-stack
voice evals system" true on sight.

## 2. Non-goals

- Not a rebuild of the report dashboard; it **reuses** the existing detail/flame
  renderers and the PRD 01/03/04 APIs.
- No auth, accounts, or saved history (stateless, ephemeral — same as the service).
- **No paid path**; the console only drives the $0 MockBackend/deterministic APIs.
- No new eval math or response schema beyond what 01/03/04 already return.

## 3. Hard constraints

1. **$0**, single origin (served by the PRD 01 service), no CORS.
2. **Cold-start-proof:** first paint from committed JSON; live calls only on user
   action, with a clear "running…" state (reuse PRD 01's pattern).
3. **Reuse, don't fork renderers.** The flame graph, findings table, verdict chips, and
   provenance vocabulary already exist — the console composes them, it does not
   re-author them.
4. **Responsive + accessible** to the same bar as the current dashboard.

## 4. Stack decision (one real choice for the owner)

**Default (recommended, $0, consistent): extend the existing vanilla-JS static
dashboard** into a console view. The repo has zero JS tooling today; keeping it that
way is cheapest, fastest to stabilize, and deploys in the same container.

**Opt-in alternative: a small React/Solid app.** Stronger "full-stack" résumé signal,
but adds a Node toolchain, a build step, and hosting surface. Choose this only if the
front-end interactivity outgrows vanilla JS. *This PRD assumes the default; if the
owner wants React, say so and the phases below adjust to add a build step.*

## 5. Console features (v1)

1. **Submit:** textarea/upload for one call or a `{calls:[...]}` set (the `INGEST.md`
   shape), with the doc-example and Barge-in presets from PRD 01.
2. **Run eval:** `POST /api/evaluate` (cached via PRD 03); render each returned call's
   **quality beside cost** one-liner + the findings table.
3. **Drill down:** open the flame graph + span/turn costs + verdict + **quality rubric**
   (from PRD 04's `quality` block) for a call, using the existing detail renderer +
   PRD 01's `details` payload.
4. **Compare / sweep:** submit a `VariantSpec` (e.g. cheaper router) → `POST
   /api/experiments` (PRD 03) → poll → show the gated `ExperimentResult` (Δcost CI,
   preservation Wilson interval, divergent exemplars) **beside** the baseline, with the
   §8.3 honesty labels intact.
5. **Honesty always visible:** every number keeps its tier badge (measured /
   instrumented / not-measured); pending judge dimensions read as pending, never as 0.

## 6. Build phases

- **P0 — Console page + submit/run** against `/api/evaluate`; quality-beside-cost row.
  *Verify:* a headless/page test loads the console, posts a preset, renders quality+cost
  with tier badges; first paint works with the API stopped.
- **P1 — Drill-down** reusing the detail renderer + PRD 01 `details`. *Verify:* opening a
  call shows the flame graph and the quality rubric together.
- **P2 — Compare/sweep** against `/api/experiments`. *Verify:* a variant submit polls to
  a gated result and renders it beside baseline with CI + preservation + divergent list;
  a queued/running/done/error state each renders.
- **P3 — Polish + a11y + responsive.** *Verify:* the existing design-audit/a11y bar is
  met; works at phone width; pinned strings/tests intact.

## 7. Definition of Done (prod-ready)

- [ ] A visitor submits a call and sees **quality beside cost** with honest tier badges,
      no install, first paint < 5 s on a cold container.
- [ ] Drill-down shows the flame graph and the PRD-04 quality rubric for a pasted call,
      reusing the existing renderer (no forked copy).
- [ ] Compare/sweep runs a variant via `/api/experiments` and shows the gated result
      (Δcost CI, Wilson preservation, divergent exemplars) beside baseline, labels intact.
- [ ] Pending judge dimensions render as pending, never as a score or 0.
- [ ] `$0`, single origin, stateless; cold-start-proof; `uv run pytest` green (incl. new
      front-end contract tests); suite not regressed.
- [ ] Responsive + a11y parity with the current dashboard.

## 8. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| Re-authoring renderers → drift/two truths | High | Compose existing renderers; a test asserts no duplicate renderer added |
| A visitor reads a pending quality dim as "0/failed" | High | Pending renders as an explicit "calibration pending" badge, never a numeral |
| Async sweep UX feels broken on cold start | Med | Explicit queued/running states; first paint from committed JSON |
| Vanilla JS gets unwieldy | Med | Keep v1 feature set fixed; React only if the owner opts in (§4) |

## 9. Out of scope / future

- React/Solid rewrite (unless opted into per §4).
- Saved runs / shareable permalinks / history.
- Multi-variant matrices beyond a baseline-vs-one-variant compare.

## 10. Handoff / dependencies

- **Depends on PRD 03 (experiments API + cache) and PRD 04 (quality block).** Build order
  for the batch: **04 and 03 first (parallel ok) → 05 last.**
- **Reviewer will check:** renderer reuse (no forks), quality+cost shown together with
  honest badges, pending dims never shown as scores, §8.3 labels intact on sweeps,
  $0/single-origin/cold-start, and no frozen-contract or eval-math changes.
