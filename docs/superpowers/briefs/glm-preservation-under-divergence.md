# Brief — preservation under divergence (modeled, on synthetic ground-truth)

**Base:** `wave0-foundation` @ `ac51367`. Branch `opencode/wave2-preservation-under-divergence`.
Reviewed + merged by Claude. **Build TDD. No paid runs** — this is a deterministic
re-analysis of existing forks + authored fixtures.

## The gap
Wave-2 measured preservation at **0.985** — but ONLY over non-divergent trials (the
cheaper model made the *same* decision). The 17/217 real forks (7.8%, paid n=250/seed 8)
are **excluded**, not re-adjudicated, so we have never watched a verdict hold or fail
when the cheaper model decides *differently*. That is the honest hole a skeptical CTO
will find: "0.985 preservation, but only where the model agreed with itself."

## The trap (name it so you do not fall in)
You **cannot** measure this by naively re-adjudicating a fork through `replay()`, because
replay **pins the downstream tools**. If nano routes to `order_status` but the trace's
tool spans still fire the original `billing_dispute` flow (pinned), re-adjudication
judges a **trace that never happened** — a pinned-tool *fiction*. Its verdict is either
structurally unchanged (H-1 again) or a frankenstein (routed X, executed Y). **Neither is
a real outcome.** Any approach that re-adjudicates a fork against pinned downstream tools
is FORBIDDEN — STOP and flag if you find yourself doing it.

## The honest ruling — a ground-truth INTENT oracle (modeled, not measured)
Judge each fork against the corpus's **ground-truth intent**, deliberately *ignoring* the
pinned downstream. The substrate already exists: `turnstile_verdict.registry` encodes each
scenario's required resolution (it is what drives the MISROUTED verdict). Extend that
same semantics to ask, per forked decision: **does the cheaper model's different decision
still serve the trace's true intent?**
- `route` fork → a route to a scenario whose registry-required resolution is incompatible
  with the trace's true `scenario_id` does NOT serve the intent (not preserved); a route
  to `other`/a safe-escalation target is a *non-resolution*, judged per its registry rule,
  never silently "preserved."
- `escalate_check` fork → `continue→escalate` hands off (typically a resolution via
  ESCALATED); `escalate→continue` drops a required handoff (typically not preserved).
  Decide from the registry + the existing adjudicator rules, not from pinned tools.
- `tool_select` / `compose` forks → decide from the registry where the required tool /
  terminal act is named; **if a fork's outcome is NOT decidable from the registry alone,
  it is UNDECIDABLE here — report it as such, never guess.**

This is a **MODELED** estimate on synthetic ground-truth (Instrumented tier), NOT a
measured number. It is **never folded into the 0.985**; it is reported as a separate
"preservation-under-divergence (modeled)" figure with its assumptions stated. The real
*measured* number requires **open-loop execution** of the divergent path (a live agent /
tool-response layer that actually runs the fork to a terminal state) — deferred, out of
scope, and named as the honest ceiling.

## Item 1 — fork forensics (free spike; owner go/no-go before Item 2)
On the 17 real forks (paid n=250/seed 8 — the result JSON is in the OpenCode clone; owner
points you at it): per fork, record kind, original label, forked label, and classify each
as (a) **outcome-decidable from the registry/intent** or (b) **undecidable without
open-loop execution**. Deliverable: `docs/PRESERVATION-DIVERGENCE-NOTE.md` with the table
+ the decidable fraction. **If too few forks are decidable to be worth an oracle, say so
and recommend deferring to open-loop** — do not build Item 2 to build it. Owner decides.

## Item 2 — the intent-preservation oracle (free build, only on Item-1 go)
- A pure function `preserved_under_divergence(trace_intent, original_decision,
  forked_decision) -> bool | None` (None = undecidable), extending
  `turnstile_verdict.registry` semantics. Every rule **stated in a docstring and
  sweepable** (the project's measure-first discipline: no unstated modeling constant).
- Apply it to the excluded forks: report `preservation_under_divergence_modeled =
  preserved / decidable`, with `undecidable` counted and listed, NEVER folded into the
  measured identity-preservation number.
- TDD on **authored fork fixtures** (`fixtures/forks/*.json` — a NEW dir, owner+Claude
  lane; do NOT touch `fixtures/golden/` or `fixtures/preservation/`): construct one
  fork per decidable kind whose ground-truth outcome is unambiguous, assert the oracle's
  verdict. Include an explicitly-undecidable case → asserts `None`.
- A re-analysis entry that runs the oracle over the real forks (no new paid calls; reads
  the existing result JSON path passed as an arg).

## Boundaries & discipline (hard)
- **NEVER touch `packages/schema/`, `fixtures/golden/`, `docs/METHOD.md`,
  `docs/LIMITATIONS.md`** (schema/fixtures/narrative = owner+Claude). Extend
  `turnstile_verdict` (registry) in-lane; do NOT weaken the existing MISROUTED / verdict
  rules. **No paid runs, no network.**
- **STOP and flag** any oracle rule you cannot justify from the scenario registry — an
  undecidable fork is an honest `None`, never a guess. Do not fold modeled numbers into
  measured ones. Do not re-adjudicate forks through pinned tools.
- Green + `ruff check packages/` clean.

## Acceptance
- Item 1 note with the fork table + decidable fraction + owner go/no-go on record.
- (On go) Oracle with every rule stated + swept; authored fork fixtures cover each
  decidable kind + an undecidable case; the real forks re-analyzed into a SEPARATE
  modeled figure with `undecidable` listed.
- The measured 0.985 identity-preservation number is untouched and never merged with the
  modeled figure.
- Open-loop execution named as the deferred real-measurement ceiling.
- Suite green, ruff clean; `schema/golden/METHOD/LIMITATIONS` diffs empty.
