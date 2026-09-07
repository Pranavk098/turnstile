# Brief — architecture-target migration (package merges + conftest cleanup)

**Base:** `wave0-foundation` @ the tip **after `opencode/wave2-exp-hardening` is merged**
(NOT 66fe8ed). Branch `opencode/arch-migrate`. Reviewed + merged by Claude.

## RUN THIS ONE ALONE, SERIALLY — not in parallel
This is workspace-wide import churn (it renames imports across `replay`, `stats`,
`agent`, `otel`, `experiments`, and conftests). It **conflicts with the exp-hardening
lane** (both touch `replay`/`stats`/`experiments`) and with any other branch. Merge
exp-hardening first, then rebase/branch this from that tip, and run nothing else in
parallel with it.

## Goal (audit Task-2 target layout — a pure refactor, zero behavior change)
- **`stats` → `replay`:** fold the stats module into replay; update the imports (the
  audit noted ~3 import sites). One source for aggregate/Wilson/bootstrap.
- **`otel` recorder → `agent`:** merge the recorder into agent. **Do NOT drop the OTel
  SDK emission and do NOT change the post-G1 timing model** — both are load-bearing; this
  is a move, not a rewrite.
- **G — conftest sys.path shims:** the root dev group installs every member editable, so
  the `verdict/pricing/corpus/detectors/conftest.py` `sys.path` inserts are likely dead.
  Verify by removing one and running that package's tests; remove all if green.

## Boundaries (hard)
- **Pure refactor: no behavior change, no number change.** The deterministic headline
  (0.57%/0.55%), the full suite, and ruff must all be identical before and after.
- NEVER touch `packages/schema/` or `fixtures/golden/`.
- Do it as small, reviewable commits (one move per commit) so the diff reads as
  mechanical relocation + import updates, not a rewrite.

## Acceptance
- Target layout reached; every import updated; no dead conftest shims left.
- Full suite green + ruff clean, with the deterministic numbers unmoved.
- OTel emission + post-G1 timing demonstrably preserved (call out the tests that cover
  them in the delivery report).
- STOP and flag if any move forces a behavior change rather than a pure relocation.
