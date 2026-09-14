# PRD 06 — improvements delegation brief

**Executor:** OpenCode · **Reviewer:** Claude · **Scope:** two hygiene follow-ups.
Docs/data/CI only — **zero `.py` behavior change** (a new test/CI script is fine).

## Global constraints

- **$0.** No hosted/paid anything.
- **Truthful claims only** (same as PRD 06): nothing in docs may overclaim.
- `uv run pytest` green; headline numbers must not move.

---

## Task 1 — regenerate the stale committed dashboard sample data (carefully)

**Why:** `packages/dashboard/sample/` is stale versus the current `build_data.py`;
running the build rewrites ~50 files (a stray-space provenance fix and similar).
PRD 06 deliberately restored the tree to avoid silent data churn inside a docs PRD —
this task does the regeneration on purpose, with proof it's cosmetic.

**Do:**
1. Run the real generator: `uv run python packages/dashboard/build_data.py`.
2. Commit the resulting `packages/dashboard/sample/*.json` changes.

**Acceptance (the guardrails matter more than the regen):**
- Produce a **diff summary** categorizing every changed file: it must be only
  provenance/whitespace/formatting — **no headline number moves** (recoverable
  margin, CPRC, per-detector findings counts, D7 values).
- Prove number-stability: `test_home` and `test_build_data` (and any dashboard test
  that pins numbers) stay green; explicitly diff the fleet headline values before/after
  and show they're identical.
- If *any* headline number changes, **stop and report** rather than committing — that
  would mean the generator drifted from the committed numbers and needs a human
  decision, not a silent update.
- Full suite green.

---

## Task 2 — CI guard so the README test count can't rot

**Why:** the README states `1008 passed, 4 skipped`. It was wrong before (said 833 /
942). Pin it the same way `test_home` pins the landing-page numbers.

**Do:** add a small check (a test, or a step in `ci.yml`) that parses the current
`pytest` pass/skip count and asserts the README's stated count matches. Prefer a test
(`packages/.../test_readme_count.py` or similar) so it runs locally too. Keep it robust
to formatting (match the numbers, not exact surrounding prose).

**Acceptance:**
- The check passes now against `1008 passed, 4 skipped`.
- Deliberately bumping the README number in a scratch edit makes the check fail
  (demonstrate once, then revert).
- No flakiness: it reads the same suite the badge reflects.

---

## Explicitly out of scope (optional, low priority)

- **Weekly external-link health job** (reports, never fails). Nice-to-have polish; the
  in-repo link-checker already covers internal links and externals are skipped by
  design to avoid flaky CI. Skip unless you specifically want it.

## Handoff

Reviewer will check: the sample regen is provably cosmetic (numbers frozen) or was
correctly halted, zero `.py` behavior change, and the README-count guard actually
fails when the count is wrong.
