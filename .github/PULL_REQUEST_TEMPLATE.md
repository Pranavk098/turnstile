<!-- Keep it small, keep it honest. -->

## What this changes

## Honesty labels

- [ ] New numbers carry a measured / instrumented / not-measured label (in the report **and** here). Unlabeled numbers are a review blocker — see CONTRIBUTING.md.
- [ ] No README/docs claim exceeds docs/METHOD.md + docs/LIMITATIONS.md.

## Checks

- [ ] `uv run pytest -q` green (or: failing tests listed below with cause)
- [ ] Frozen contracts untouched (`turnstile-prd.md` §3–5, `packages/schema`, pricing formulas) — or the contract change is called out explicitly above
- [ ] No paid path touched (no new outbound calls; `TURNSTILE_ALLOW_PAID=1` + `OPENAI_API_KEY` still required for all spend)
- [ ] Docs-only PRs: no code behavior changed

## Notes for the reviewer
