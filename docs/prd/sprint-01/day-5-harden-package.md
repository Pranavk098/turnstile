# Day 5 PRD — Production hardening + packaging + release

**Inherits `00-charter.md` in full.** Executor: OpenCode · Reviewer: Claude · Depends on:
Days 1–4 · Feeds: Day-6 (install docs), Day-7 (release announce).

## Objective
Take the project from "green repo" to **installable, secure, observable, versioned
v0.1.0** — the "robust level."

## Connection (charter §5)
Wraps everything Days 1–4 built: packages the libraries, scans the supply chain, adds
service observability (consuming Day-3's counters), and cuts the release Day-6 documents
and Day-7 announces. MUST NOT change runtime contracts (charter §4).

## Day-specific strict rules (add to charter §1)
- The green gate is absolute: a security finding **at or above the release threshold**
  (e.g. `high`) MUST block the release, not be waived.
- Published packages MUST install in a **clean venv with no dev deps** and pass a smoke
  command; the working tree MUST NOT be required.
- Secrets (Sentry DSN, PyPI token) MUST come from CI secrets, MUST NOT be committed, and
  MUST NOT be required for the $0 default runtime.

## Priority factors
### P0 — base case (MUST)
1. **PyPI packaging** for the core libraries (schema/pricing/verdict/detectors/replay/
   ingest/quality) under a namespace, installable + smoke-tested from a clean venv.
2. **Supply-chain CI**: `pip-audit` + `bandit` + GitHub **CodeQL** + **Dependabot**;
   findings triaged; threshold gate wired.
3. **Observability**: structured logging + **Sentry (free tier)** on the service; a
   `/metrics` endpoint (extends Day-3 counters).
4. Fix the **Node 20 CI deprecation** (bump actions).
5. **v0.1.0** tag + `CHANGELOG.md`.

### P1 — build-on-top (SHOULD)
6. **Load test** (k6/locust free) → documented limits + a sustained-throughput number.
7. Publish the container image to **GHCR**; add an **SBOM**.
8. The optional weekly external-link-health job (deferred item, now cheap).

### P2 — stretch (MAY)
9. A signed release. 10. A staging environment note / blue-green sketch.

## Latency budget (charter §2, tightened)
- `/metrics` MUST respond **< 50 ms**; structured logging MUST add **< 5 ms/request**.
- The load test MUST sustain the throughput target at **p95 < 300 ms** (target set from
  Day-3's measured numbers).

## Interfaces
Per-package `pyproject` publish metadata; a namespace (e.g. `turnstile-<pkg>`); a
`smoke` console entry point; CI jobs (`security`, `codeql`); `/metrics`; Sentry init
behind an env DSN (no-op when unset); `CHANGELOG.md`; a `release` workflow.

## Acceptance criteria (EARS)
- WHEN a user runs `pip install turnstile-<pkg>` in a **clean venv**, the import SHALL
  succeed and the smoke command SHALL exit 0. *(check: fresh-venv install + smoke, dynamic)*
- IF `pip-audit` or CodeQL reports a finding at/above threshold, THEN the release job
  SHALL fail. *(check: run the scanners in CI; confirm the gate)*
- WHEN the service raises an unhandled error, THEN it SHALL emit a structured log line and
  a Sentry event. *(check: induce a fault against the running service, read log + Sentry)*
- WHILE no Sentry DSN is set, the service SHALL run identically with observability inert.
  *(check: boot with DSN unset)*
- The v0.1.0 tag SHALL point at a commit whose CI is fully green. *(check: tag → run status)*

## Recursive loop — Day-5 dynamic checks (charter §3)
Install each package into a **fresh venv** and run its smoke; run all scanners and confirm
the threshold gate actually fails on a seeded finding then passes when clean; induce a
service fault and confirm the structured log + Sentry event; run the load test and confirm
the throughput/p95. Iterate until every gate is green. A missing PyPI/Sentry credential is
an **environmental blocker** (needs the owner) — wire everything and report what needs a
secret, rather than faking success.

## Risks & mitigations
- Broken clean-venv install (hidden dev-dep) → the fresh-venv smoke catches it each loop.
- Scanner noise blocking release → triage + documented, justified suppressions (never blanket).
- Secret leakage → CI secrets only; a scan for committed secrets in the loop.

## Out of scope
A hosted multi-tenant SaaS; a paid monitoring tier.

## Reviewer gate (Claude)
Clean-venv install + smoke green; scanners gating correctly; observability proven by an
induced fault; Node20 fixed; v0.1.0 on a green commit; runtime contracts unchanged; CI green.
