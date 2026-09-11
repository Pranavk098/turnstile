# Brief — Live agent Phase 5: fair open-loop with function-calling

**Base:** `wave0-foundation` @ `fbed5e7` (rebase onto Phase-4's tip once it merges; both live
in `packages/live/`). Branch `opencode/live-p5-functioncalling`. Reviewed + merged by Claude.
**Owner-gated paid, budget-capped $2. Build TDD.**

## Goal
Make the open-loop preservation-under-divergence number **fair**. Phase 3 measured 0/0, but
partly as a harness artifact: the cheaper model was asked to emit a *label* and it *composed*
prose instead of acting. Real agents use **function-calling** — give the model the tools as
actual functions and it can *invoke* them. Re-measure open-loop preservation with
function-calling, so we answer the real product question honestly: **is routing to a cheaper
model actually safe, or does it genuinely fail to act?**

## Mechanism
- **A function-calling policy** (new, alongside `CappedLlmPolicy`): pass the scenario's tools
  as OpenAI `tools`/function schemas (including the registry-required terminal tool). The
  capped `gpt-5-mini` model can now **call a tool**; when it does, the existing mock tool
  runs and commits (single-source `_tools_for`). No verbatim-label elicitation.
- **Reuse the Phase-3 `openloop.py` harness unchanged in spirit:** drive each conversation
  open-loop with this policy; a conversation is divergent when its path differs from baseline;
  judge divergent conversations under BOTH existing rules — rule 1 registry-grounded (did it
  invoke + commit the required tool?), rule 2 the LLM judge — **reported separately, never
  folded.**
- Run at **n ≈ 30–50**. Report both figures with `n_divergent`, and **compare head-to-head
  with the Phase-3 label-elicitation 0/0** so the delta from "talk" → "function-calling" is
  explicit and honest.

## Boundaries (hard)
- `packages/live/` only (a function-calling policy + wiring into `openloop.py`). **NEVER
  touch** `turnstile_agent`, `packages/schema`, `fixtures/golden`, `docs/METHOD.md`,
  `docs/LIMITATIONS.md`. Claude lands the number.
- Owner-gated paid, free bucket (`TURNSTILE_PAID_MODEL_CAP=gpt-5-mini`), **STOP if estimate
  > $2.**
- Keep the two rules **separate**, never folded into each other, the 0.98 identity figure, or
  the Phase-3 label result. Undecidable (lookup/unregistered) stays None, listed.
- **STOP and flag** if function-calling still yields ~0 divergence or ~0 resolution — that
  would itself be a real finding (report it, don't force a number).
- TDD the policy (a fake function-calling client) + the tool-commit path; green + ruff clean.

## Acceptance
- Open-loop preservation re-measured with **function-calling**, both rules separate, n ≥ 30,
  with `n_divergent` and a direct comparison to the Phase-3 label 0/0.
- The honest question answered: does the cheaper model *act* when given real tools? (Whatever
  the answer — higher preservation, or still low — it's reported straight.)
- `packages/live/` only; harness/schema/golden/METHOD untouched; suite green; ruff clean;
  spend ≤ $2 reported.
- Delivery report: both figures, n_divergent, the Phase-3 delta, actual spend, and 2–3
  example divergent conversations (did the cheap model call the tool, or still just talk?).
