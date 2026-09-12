# Brief — Live agent Phase 5 scale: firm up the fair open-loop number

**Base:** `wave0-foundation` @ `2d895b5` (`git pull && uv sync`). Branch
`opencode/live-p5-scale`. Reviewed + merged by Claude. **Owner-gated paid, budget-capped $2.**
Build on `docs/superpowers/briefs/glm-live-p5-functioncalling-openloop.md` (the n=36 probe
this scales).

## Goal
The fair open-loop number (**42.9% registry / 11.1% judge**) is real but rests on n=36 with 9
divergent conversations — too thin for a CI. Scale it: extend the probe set well beyond v36
so we get a real `n_divergent` and a bootstrap CI on both figures, and can say whether 42.9%
holds or was small-n luck.

## Mechanism
- Reuse the Phase-5 `FunctionCallingPolicy` and the `openloop.py` harness **unchanged in
  spirit**. The only new work is **more probe conversations**: author ~60–100 conversations
  across the 6 scenarios, balanced, **designed to actually diverge** (the whole measurement is
  conditional on divergence — a probe that never forks teaches nothing).
- Re-run at the larger n. Report **both rules separately** — rule 1 registry-grounded (invoked
  + committed the required tool?), rule 2 the LLM judge — each with `n_divergent` and a
  bootstrap CI. **Never fold the two**, and never fold either into the 0.985 identity figure
  or the Phase-3 label result.
- Report the **n=36 → large-n delta** explicitly, so the tightening (or the surprise) is
  visible and honest.

## Boundaries (hard)
- `packages/live/` only (more probe scripts + any wiring). **NEVER touch** `turnstile_agent`,
  `packages/schema`, `fixtures/golden`, `docs/METHOD.md`, `docs/LIMITATIONS.md`. Claude lands
  the number.
- Owner-gated paid, free bucket: `export TURNSTILE_ALLOW_PAID=1` +
  `export TURNSTILE_PAID_MODEL_CAP=gpt-5-mini`. **STOP if the worst-case estimate > $2**
  (use `enforce_budget`, now parameterized).
- Undecidable (lookup/unregistered) stays `None`, listed — never coerced to a pass or fail.
- **STOP and flag** if divergence collapses to ~0 at scale — that would itself be a real
  finding; report it, don't force a number.
- TDD any new harness code; suite green; `ruff check packages/` clean.

## Acceptance
- Open-loop preservation re-measured at n ≥ 60 with both rules separate, each with
  `n_divergent` and a bootstrap CI, plus the n=36 → large-n delta.
- `packages/live/` only; harness/schema/golden/METHOD untouched; suite green; ruff clean;
  spend ≤ $2 reported.
- Delivery report: both figures + CIs, `n_divergent`, the delta vs n=36, actual spend, and
  2–3 example divergent conversations (did the cheap model call the tool, or just talk?).
