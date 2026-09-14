# CONTRIBUTING

## Setup

Only `uv` is required — no keys, no local models, no paid anything for the
default path:

```bash
uv sync
uv run pytest -q
make demo        # builds the report, serves it at localhost:8000
make serve       # dashboard + live eval engine at localhost:8000
```

## Contract-first rule (load-bearing)

`turnstile-prd.md` §3–5 and `packages/schema` are **frozen contracts**. Do not
edit them to make a feature fit — change the feature, or propose the contract
change explicitly in the PR so it gets reviewed as one. The same applies to
the pricing formulas (`pricing/rates.yaml` + `packages/pricing`): rates change
with dated source URLs, never with hardcoded edits in logic.

Related: the paid-measurement path stays hard-gated. Nothing you add may spend
money unless `TURNSTILE_ALLOW_PAID=1` and `OPENAI_API_KEY` are both set, and it
must ask before every run. The default test/CI path must never need either.

## Honesty labeling (required on every number)

Any new number a PR introduces must carry one of the three labels, in the
code/report *and* in the PR description:

- **measured** — real synthesis, exact arithmetic, or gated replay, with
  provenance and (where applicable) confidence intervals;
- **instrumented** — the mechanism runs but the magnitude is not claimed;
- **not measured** — openly stated, with the path that would measure it.

An unlabeled number is a review blocker. Absent data reads ABSENT, never zero
— see `docs/INGEST.md` ("Acoustic absence") for the established pattern. Check
`docs/METHOD.md` / `docs/LIMITATIONS.md` before quoting or extending a claim.

## Commit / PR conventions

- Small, focused commits; present tense ("add D7 preset to eval panel").
- Every PR fills in `PULL_REQUEST_TEMPLATE.md` completely — especially the
  honesty-label checkbox and the "no code behavior changed" line when
  docs-only.
- Keep the suite green: `uv run pytest -q` before pushing. If you touch the
  dashboard's data contract, run `uv run python packages/dashboard/build_data.py`
  and confirm the tree diff contains only what you intended.
- By contributing, you agree your work lands under the repo's Apache-2.0
  license (see LICENSE; attributions in NOTICE).
