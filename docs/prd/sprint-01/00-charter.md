# Sprint 01 — Charter (binding preamble for all 7 day-PRDs)

**Status: binding.** Day-1…Day-7 PRDs in this folder each inherit this charter in full.
Where a day-PRD is silent, this charter governs. A day-PRD MAY tighten a budget or rule;
it MUST NOT loosen one. These are **executable specs** (spec-driven development): the
spec is the source of truth, the agent drives it, and "done" is *proven by dynamic
checks against the running system*, never asserted.

## 0. How to read these PRDs (conventions)

- **Rule keywords are RFC-2119.** MUST / MUST NOT = hard, non-negotiable. SHOULD =
  strong default, deviate only with a recorded reason. MAY = optional.
- **Acceptance criteria use EARS** (Easy Approach to Requirements Syntax), so every
  criterion is unambiguous and machine-verifiable:
  - Ubiquitous: *The <system> SHALL <response>.*
  - Event: *WHEN <trigger>, the <system> SHALL <response>.*
  - State: *WHILE <state>, the <system> SHALL <response>.*
  - Unwanted: *IF <condition>, THEN the <system> SHALL <response>.*
  - Optional: *WHERE <feature present>, the <system> SHALL <response>.*
  Every acceptance criterion MUST carry a **quantified threshold** and a **named
  dynamic check** that proves it.
- **Priority tiers.** **P0 = base case** (MUST ship for the day to count as done).
  **P1 = build-on-top** (SHOULD, only after every P0 gate is green and budget remains).
  **P2 = stretch** (MAY). A day MUST NOT start P1 while any P0 gate is red.

## 1. Global strict rules (MUST / MUST NOT — all seven days)

1. **$0.** No paid hosting and **no paid API call in any CI job or default runtime path**.
   The only permitted spends are the two explicitly flagged (Day-2 real-data acquisition,
   Day-4 reference-labeler); each MUST be opt-in behind an env flag, logged, and absent
   from CI.
2. **Engine purity.** Services, UIs, docs, and scripts MUST NOT re-implement or fork the
   pricing / verdict / detector / replay / quality math. They call the existing entry
   points and render the result.
3. **Frozen contracts.** `packages/schema` (§3–5 of `turnstile-prd.md`) and the pricing
   formulas MUST NOT change. The **shared runtime contracts** below MUST NOT be broken by
   a downstream day; a day that must change one updates §4 here **and every consumer in
   the same PR**.
4. **Honesty discipline.** Every surfaced number MUST carry a tier
   (measured / instrumented / not-measured). No uncalibrated model score MUST reach a
   headline or the beside-cost line. No fabricated or mislabeled data. No claim without a
   traceable source.
5. **Green gate.** `uv run pytest` MUST stay green and **CI on the pushed tip MUST be
   green** at the end of every day. A day that ends CI-red is not done.
6. **Determinism.** Outputs that are deterministic MUST stay byte-stable across a change
   unless changing them **is** the feature; the golden fleet headline MUST stay
   byte-identical unless a PRD explicitly authorizes a move.

## 2. Performance contract ("as responsive as real-time" — RAIL + API)

Inherited by every day; a day MAY tighten, never loosen. Every budget below is a
**gate**, verified by a dynamic measurement, not an aspiration.

- **Response (user input → visible reaction): < 100 ms**, with a **50 ms** processing
  budget (RAIL). Anything slower breaks the felt action→reaction link.
- **Animation: 60 fps**, ≤ 16 ms/frame (≤ 10 ms render).
- **Load: interactive < 5 s cold** on a free-tier container / mid-range device;
  **< 1.5 s warm**.
- **API:** read endpoints **p95 < 200 ms warm**; a **cache-hit eval p95 < 50 ms**; any
  operation that can exceed **1 s MUST be asynchronous** (job + poll), never a blocking
  request. First byte on a cold container MUST still occur from committed data.

## 3. The Recursive Self-Verification Loop (MANDATORY — the core of every day)

Every feature slice MUST be delivered through this loop. "It compiles / unit tests pass"
is **not** done. Done is: the **running** feature observed to meet every acceptance
criterion and budget, with a captured transcript.

```
LOOP per slice (hard cap: 6 iterations):
  1. BUILD the slice.
  2. DYNAMIC CHECK against the RUNNING system — not only unit tests:
       - boot the real server/app (preview_start / uvicorn / mkdocs serve),
       - drive the real surface (curl, Browser/Chrome MCP, Playwright-style clicks),
       - MEASURE real latency against the §2 budgets,
       - read real logs (preview_logs) for errors/warnings.
  3. COLLECT every defect: functional bug, 4xx/5xx, console error, budget miss,
       regression, honesty/label violation, contract break.
  4. If the defect list is non-empty: FIX the highest-severity defect, then GOTO 2.
  5. If empty: the slice is done — attach the dynamic-check transcript to the PR.
  IF the cap is hit with defects still open: STOP, do NOT ship red, and report the
  blocking defect(s) with evidence and a proposed fix for human review.
```

Rules for the loop:
- The agent MUST NOT mark a slice done on assertion; a **dynamic-check transcript**
  (HTTP responses, measured timings, screenshots/DOM reads, benchmark output, scanner
  output) MUST be attached as evidence.
- The agent MUST fix root causes, not silence checks. Loosening a threshold or deleting a
  failing check to go green is a **charter violation**.
- The loop MUST re-run the **full** acceptance set after each fix (no partial "it should
  still pass") — regressions are defects.
- When blocked at the cap, the report MUST distinguish *environmental* blockers (needs a
  human: an account, a secret, a paid step) from *code* defects.

## 4. Shared runtime contracts (the connective tissue — MUST NOT break silently)

These are what make the seven days one system. A day consumes upstream contracts and
MUST preserve them for downstream days.

- **Report shape** (`data.json` / `/api/*` responses): fleet + calls[] + findings[] +
  per-call details{trace, span_costs, turn_costs, verdict, findings, **quality**,
  _provenance} + provenance/tier labels. Additive changes only.
- **`/api/*` surface** (Day-1): `/health`, `/api/fleet|calls|calls/{id}|example|ingest`,
  `POST /api/evaluate` (→ artifact + `details`), `POST /api/experiments` + `GET
  /api/experiments/{id}` (Day-3 async). Additive changes only.
- **Ingest contract** (`IngestCall`, `docs/INGEST.md`) + the `decision_kind` honesty
  boundary (inferred labels never feed a measured D1) — every provider adapter obeys it.
- **Quality block** (`turnstile_quality`) + the calibration gate — no score without a
  passing calibration.
- **Provenance/tier vocabulary** — measured / instrumented / not-measured, shown verbatim.

## 5. Dependency map (build order & what flows where)

```
Day1 LIVE SERVICE ───────────────► substrate for everything
   ├─ Day2 REAL DATA ──────────────► surfaces on Day1; credibility for Day7
   ├─ Day3 SPEED + OBSERVABILITY ──► speeds Day1/2; metrics feed Day5; numbers feed Day6/7
   ├─ Day4 CALIBRATED QUALITY ─────► surfaces on Day1 UI + Day6 docs
   ├─ Day5 HARDEN + PACKAGE + v0.1.0 ─► wraps Days1-4; feeds Day6 install + Day7 release
   ├─ Day6 DOCS + ASSETS ──────────► documents Days1-5; links live URL/PyPI/PERF; feeds Day7
   └─ Day7 LAUNCH ─────────────────► depends on ALL prior gates being green + live
```
A downstream day MUST NOT ship if it breaks an upstream gate; the pre-launch QA (Day-7)
re-verifies every day's DoD against the live surfaces.

## 6. Per-day reviewer gate (Claude)

A day is accepted only when: every P0 EARS criterion passes its dynamic check; every §2
budget it touches is measured green; the §1 invariants hold; the §4 contracts are intact;
CI on the tip is green; and the dynamic-check transcripts are attached. P1/P2 are bonus,
never a substitute for a green P0.
