# PRD 06 — OSS hygiene + two-audience README (Apache-2.0)

**Owner (spec):** Pranav Koduru · **Executor:** OpenCode · **Reviewer:** Claude
**Status:** ready to build · **Roadmap item:** #6 (packaging for adoption + resume)

---

## 1. Thesis

The engineering content is strong; the packaging throttles it. A stranger can't tell
in 30 seconds what this is or try it, there is no license (so no one can legally
use it), and the README speaks to only one audience. This feature makes the repo
**adoptable and legible to two audiences at once**: a recruiter/engineer who wants a
URL and a 30-second story, and a technical reader who wants the honesty method in
full. It also adds the standard OSS scaffolding a serious project has.

License decision (confirmed): **Apache-2.0.**

## 2. Non-goals

- **Do not weaken or restyle the honesty framing.** METHOD/LIMITATIONS and the
  measured/instrumented/not-measured discipline are the product's differentiator;
  the README rewrite must *foreground* them, not smooth them into marketing.
- No per-file license headers (noise for a solo repo) — LICENSE + NOTICE + pyproject
  metadata is the Apache-2.0 convention adopted here.
- No renaming, restructuring packages, or changing any code behavior. Docs, metadata,
  and repo-hygiene files only.
- No CI pipeline redesign beyond adding the badge + the keyless-demo check (§4).

## 3. Hard constraints

1. **$0.** Docs/metadata only; nothing to host or run that costs money.
2. **Truthful claims only.** Every number or capability the README states must match
   METHOD/LIMITATIONS and be currently true in the repo. No aspirational metrics in
   the README. If PRD 01's live URL isn't deployed yet, the demo link is a clearly
   marked placeholder, not a dead promise.
3. **`make demo` must work from a clean clone with only `uv`** — no keys, no WSL, no
   local models. (It nearly does today; this PRD makes it a guarantee.)

## 4. Deliverables

- **`LICENSE`** — full Apache-2.0 text. Copyright: `Copyright 2026 Pranav Koduru`.
- **`NOTICE`** — Apache-2.0 NOTICE stub with project name + copyright.
- **`README.md` rewrite**, two-audience structure (§5).
- **`CONTRIBUTING.md`** — how to set up (`uv sync`), run tests (`uv run pytest`), the
  contract-first rule (don't edit frozen §3–5), commit/PR conventions, and the
  honesty-labeling expectation for any new number.
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant, contact = the owner's email.
- **`SECURITY.md`** — how to report an issue privately; note the tool reads traces
  and makes no outbound calls on the free path.
- **`.github/ISSUE_TEMPLATE/`** (bug + feature) and **`PULL_REQUEST_TEMPLATE.md`** —
  the PR template includes a checkbox: "new numbers carry a measured/instrumented/
  not-measured label."
- **`pyproject.toml`** (root + packages as appropriate): `license = "Apache-2.0"`,
  `authors`, `description`, `readme`, `urls` (repo, demo), and trove `classifiers`.
- **CI badge** in the README (tests passing) + a CI job that runs `make demo` headless
  on a clean checkout with **no secrets available** to prove the keyless path.
- **Link check** over the README/docs so no doc link 404s.

## 5. README structure (the two-audience contract)

```
# Turnstile
> one-line what-it-is (voice-AI margin profiler + the eval nobody runs: cost)

[ ▶ Live demo (URL) ]   [ tests: passing ]   [ Apache-2.0 ]      ← 30-second row

## 60-second story           ← recruiter/engineer audience
  - what it does, in plain words (price → verdict → detect → replay → report)
  - the one number that started it (barge-in ~4% on real Piper), honestly labeled
  - "See it": the live demo URL (zero install)

## The honesty rule          ← the differentiator, up high, not buried
  - measured / instrumented / not-measured, with one example of each
  - links to METHOD.md and LIMITATIONS.md

## How it works              ← technical audience
  - the pipeline diagram, the packages that carry weight
  - run it: uv sync / uv run pytest (current pass count) / make demo
  - run it on YOUR calls: docs/INGEST.md (+ the Vapi adapter from PRD 02)

## Status & limitations       ← unprompted honesty, links out
## License (Apache-2.0)
```

The existing README's substance is largely reusable — this is a restructure for two
audiences with the live-demo link added and the honesty rule promoted, **not** a
rewrite of the technical claims.

## 6. Build phases

- **P0 — License + metadata.** `LICENSE`, `NOTICE`, `pyproject` license/authors/urls/
  classifiers. *Verify:* GitHub's license detector recognizes Apache-2.0; `uv sync`
  still resolves; `python -c "import tomllib"` parse check on every edited pyproject.
- **P1 — README rewrite** (§5). *Verify:* renders correctly; every claimed number
  traces to METHOD/LIMITATIONS; test count matches `uv run pytest` output; demo link
  present (placeholder-marked if PRD 01 not yet live).
- **P2 — Community/hygiene files.** CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue/PR
  templates. *Verify:* files exist, links resolve, PR template has the honesty-label
  checkbox.
- **P3 — CI badge + keyless-demo job + link check.** *Verify:* CI green; the
  `make demo` job runs on a clean checkout **with no secrets** and produces the
  report; link-check passes.

## 7. Definition of Done (prod-ready / feature-ready)

- [ ] `LICENSE` is Apache-2.0 and recognized as such by GitHub; `NOTICE` present;
      `pyproject` declares Apache-2.0 + author + repo/demo URLs + classifiers.
- [ ] README opens with a 30-second row (demo link, tests badge, license), tells the
      60-second story, **promotes the honesty rule high**, and keeps the deep
      technical section with correct, current numbers.
- [ ] CONTRIBUTING / CODE_OF_CONDUCT / SECURITY / issue + PR templates present and
      accurate; PR template enforces the measured/instrumented/not-measured labeling.
- [ ] `git clone` → `uv sync` → `make demo` works with **no keys, no WSL, no local
      models**, proven by a secretless CI job.
- [ ] No doc link 404s (link check green).
- [ ] Full test suite still green; **no code behavior changed**.
- [ ] Every README claim is true today (no aspirational metrics; demo link marked
      placeholder if #1 isn't deployed yet).

## 8. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| README overclaims (drifts from METHOD/LIMITATIONS) | High | §7 checkbox: every number traced to a source doc; reviewer diff-checks against METHOD |
| Dead demo link | Med | Link marked placeholder until PRD 01 deploys; link-check job |
| Apache headers/attribution done wrong | Low | Use canonical Apache-2.0 LICENSE + NOTICE text verbatim; no per-file headers |
| `make demo` breaks on clean clone (hidden dep on local state) | Med | Secretless CI job on a fresh checkout catches it |

## 9. Out of scope / future

- Changelog automation, release tagging, PyPI publication.
- Docs site (mkdocs/Sphinx) — README + `docs/*.md` suffice for now.
- Per-file license headers.

## 10. Handoff notes

- Depends softly on PRD 01 (demo URL) and PRD 02 (Vapi "run on your own calls"
  line). Land it **last** of the three so both links are real; until then, mark them
  as coming-soon rather than shipping dead links.
- **Reviewer (Claude) will check:** README claims vs. METHOD/LIMITATIONS (no
  overclaim), Apache-2.0 correctness, the secretless `make demo` job actually runs
  keyless, honesty framing is promoted not diluted, and zero code behavior changed.
