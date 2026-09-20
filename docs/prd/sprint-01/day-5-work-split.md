# Day 5 — Work Split (delegation plan for parallel sessions)

**Inherits `00-charter.md` and `day-5-harden-package.md` in full.** This document
only *decomposes* the day-PRD into delegable parts; it does not loosen any rule. Where
this document is silent, the day-PRD and charter govern.

Each **Part** below is one working session. Parts in the same wave have **disjoint file
ownership** and may run in parallel. Every part MUST be delivered through the charter §3
Recursive Self-Verification Loop (hard cap 6 iterations), with a dynamic-check
transcript attached as evidence. "Unit tests pass" is never done.

---

## 0. Ground truth (verified against the repo — do not re-assume)

These facts were checked against the code on Day-5 morning. Sessions MUST treat them as
the starting state and MUST NOT "rediscover" contradictory assumptions:

1. **Day-4 remainder is exactly one artifact.** `fixtures/calibration/selection.json`
   EXISTS, `fixtures/calibration/labels.jsonl` EXISTS (120 rows = 60 calls × 2 dims),
   `fixtures/calibration/reference_log.jsonl` EXISTS, but
   `fixtures/calibration/calibration_report.json` does NOT exist. The remainder is:
   run Day-4 Part B's builder over the committed labels → generate + commit the report
   (Day-4 Part E steps 3–4). Tracked as **Track 0** below; it blocks ONLY Part H (the
   v0.1.0 tag) and the Day-4 Part F conditional — it does NOT block Parts A–D.
2. **All shippable libraries are version `0.0.0`.** `packages/{schema,pricing,verdict,
   detectors,replay,ingest,quality}/pyproject.toml` each carry `version = "0.0.0"`.
   (`packages/agent` is already `0.1.0`; root `pyproject.toml` is `0.0.0`.) No package
   has a `smoke` console entry point, no `[project.scripts]` section exists anywhere,
   and no publish metadata (README/license/classifiers beyond the basics) is release-ready.
   Version bumps to `0.1.0` belong to Part H ONLY (single writer — see §10).
3. **Workspace layout blocks naive `pip install`.** The 7 libraries declare
   `[tool.uv.sources] <dep> = { workspace = true }` (verified: `quality` depends on
   `turnstile-schema` + `turnstile-verdict` via workspace; `service` on schema/ingest/
   pricing/replay via workspace). A clean-venv `pip install` from PyPI therefore needs
   real versioned requirements, NOT workspace pins. Part A MUST resolve this (publishable
   `dependencies` with floor pins) without breaking `uv sync` in this repo.
4. **No security surface exists.** No `.github/dependabot.yml`, no CodeQL workflow, no
   `pip-audit`/`bandit` job, no suppression file. `ci.yml` has exactly two jobs (`test`,
   `keyless-demo`) plus `links`, all on `actions/checkout@v4` + `astral-sh/setup-uv@v5`.
   `keepwarm.yml` uses no checkout at all (curl only). The "Node 20 deprecation" fix is:
   bump `actions/checkout@v4` → `@v5` (node24) and `astral-sh/setup-uv@v5` → `@v6` (or
   latest major) in `ci.yml` — verify the current major tags at implementation time and
   record what was chosen and why.
5. **No observability surface exists.** `grep` for `sentry|structlog|/metrics` across
   `packages/service/src/`, `packages/service/pyproject.toml`, and root `pyproject.toml`
   returns NOTHING. What Day-3 built instead (do NOT duplicate): `GET /api/status` with
   `cache{entries,byte_size,hits,misses,hit_rate}` + `timings_ms{evaluate_median,
   evaluate_p95,source}` over a bounded 512-sample deque, `EvalCache.stats()`, and job
   `timings{queue_ms,run_ms}` (pinned by `test_observability.py`). `/metrics` MUST extend
   these counters, not re-implement them (charter §1.2 engine purity applies to
   observability wiring too: read Day-3's counters, don't fork them).
6. **No release machinery exists.** No `CHANGELOG.md`, no `v*` tag (`git tag --list "v*"`
   is empty), no `release` workflow, no GHCR publish, no SBOM. `Dockerfile` (python:3.12-
   slim, `uv sync --frozen --no-dev --package turnstile-service`) and `render.yaml`
   (free web service, `healthCheckPath: /health`) are the deploy substrate — Part E
   extends them, never replaces them.
7. **No paid/monitoring dep is installed.** `uv pip list` shows no `sentry`, `bandit`,
   `pip-audit`, `k6`, or `locust`. Sentry SDK is a NEW dependency owned by Part C;
   scanner tools run in CI (not vendored). Charter §1.1 holds: Sentry DSN and PyPI token
   come from CI secrets / env, MUST NOT be committed, MUST NOT be required for the $0
   default runtime.
8. **Day-3 PERF.md numbers are the load-test baseline.** Per-trace p95 ≈ 156 µs,
   serial matrix median 0.809 s (n=250), parallel 0.182 s (8 workers, 4.46×). The Day-5
   load target (p95 < 300 ms sustained) MUST be set from these measured numbers, not
   invented — Part E derives its target from PERF.md + a live `/api/evaluate` warm
   measurement taken at implementation time.
9. **Test command:** `uv run pytest` (workspace root). CI on the pushed tip MUST be
   green at end of day (charter §1.5). Charter §1.6 byte-stability holds: the golden
   fleet headline MUST stay byte-identical — Day 5 changes packaging/observability/CI
   only, never engine math or committed data bytes.

---

## 1. Wave plan & dependency graph

```
Track 0 (1 session, starts immediately, finishes before H):
    Part Z  Day-4 remainder: builder run → calibration_report.json → commit
            (Day-4 Parts B/E leftover; uses Day-4 work-split, not this doc)

Wave 1 (4 parallel sessions, disjoint files — start all four at once):
    Part A  PyPI packaging + clean-venv smoke (P0 #1)
    Part B  Supply-chain CI: pip-audit + bandit + CodeQL + Dependabot (P0 #2)
    Part C  Observability: structured logging + Sentry + /metrics (P0 #3)
    Part D  Node-20 fix + release workflow + CHANGELOG scaffolding (P0 #4, #5-partial)

Wave 2 (after C is merged; needs the /metrics + logging surface live):
    Part E  Load test + GHCR image + SBOM + link-health job (P1 #6, #7, #8)

Final (1 session, sequential — after Z, A–E all green):
    Part H  Integration gate: version bumps, full dynamic set, tag v0.1.0, CI green
```

**File-ownership matrix (hard boundaries — touching another part's files is a defect):**

| Part | Owns (create/edit) | MUST NOT touch |
|---|---|---|
| Z | `fixtures/calibration/calibration_report.json` (generated), Day-4 builder/CLI files per `day-4-work-split.md` | Day-5 files, service, CI, versions |
| A | `packages/{schema,pricing,verdict,detectors,replay,ingest,quality}/pyproject.toml` (publish metadata), `scripts/smoke_clean_venv.sh` (new), per-package `smoke` entry point module (new files only) | `packages/service/**`, `packages/agent/**`, `.github/**`, `CHANGELOG.md`, any `version` field (H owns) |
| B | `.github/workflows/security.yml` (new), `.github/workflows/codeql.yml` (new), `.github/dependabot.yml` (new), `scripts/security/` (new dir: suppressions + triage notes) | `.github/workflows/ci.yml`, `release.yml`, `image.yml`, any `src/` file |
| C | `packages/service/src/turnstile_service/observability.py` (new), `packages/service/src/turnstile_service/app.py` (metrics/logging/Sentry wiring only), `packages/service/pyproject.toml` (`sentry-sdk` dep only), `packages/service/tests/test_metrics.py` (new) | library pyprojects, `.github/**`, engine math, Day-3 counters in `cache.py`/`jobs.py` (read-only use) |
| D | `.github/workflows/ci.yml` (action bumps only), `.github/workflows/release.yml` (new), `CHANGELOG.md` (new), `.github/workflows/link-health.yml` (new) | `security.yml`, `codeql.yml`, `image.yml`, any `src/`, any `version` field |
| E | `scripts/load/` (new dir), `Dockerfile` (GHCR labels only), `.github/workflows/image.yml` (new) | `ci.yml`, `security.yml`, `release.yml`, service logic, versions |
| H | `version` fields (7 libs `0.0.0` → `0.1.0`), `v0.1.0` tag, PR evidence | changing any logic to go green |

**Why `version` is owned by H:** six parts touch packaging/CI/service; letting each bump
versions guarantees a conflict and an untagged half-release. Parts A–E MUST leave every
`version` field exactly as found; H sets `0.1.0` once, on the fully-green tip, then tags.

---

## 2. Track 0 / Part Z — Day-4 remainder (P0, predecessor to H only)

**Goal.** Close the single remaining Day-4 artifact so Part H can tag honestly.

**This is NOT a Day-5 session** — execute it per `day-4-work-split.md` Parts B/E:

1. If Day-4 Part B's `calibration_study.py` (κ/ECE/builder/report writer) is not yet
   committed, finish it first (known-answer tests mandatory).
2. Run the builder over the committed `fixtures/calibration/labels.jsonl` (120 rows)
   → write `fixtures/calibration/calibration_report.json` (per-dim `n_labels`, `kappa`,
   `ece`, `confusion_matrix`, `passes_gate`, provenance: labels sha256, tool version,
   timestamp, binning rule).
3. Re-derivation proof: re-run the builder from clean state → byte-identical report.
4. Commit labels + log + spot-checks + report together. `uv run pytest` green.

**Acceptance:** `calibration_report.json` committed; re-derivation transcript attached;
either `passes_gate: true` (Day-4 Part F MAY then be considered per its precondition)
or an honest shortfall statement (gate stays closed — valid P0 outcome, do NOT lower the
bar). **Parts A–D MUST NOT wait for Z.**

---

## 3. Part A — PyPI packaging + clean-venv smoke (P0 #1)

**Goal.** The 7 core libraries (`schema/pricing/verdict/detectors/replay/ingest/quality`)
installable from a clean venv with no dev deps, verified by a smoke command — working
tree NOT required.

**PRD refs.** Day-5 P0 #1; strict rule "MUST install in a clean venv with no dev deps
and pass a smoke command"; EARS #1 (fresh-venv install + smoke, dynamic).

### Steps

1. **Publish metadata** (the 7 library `pyproject.toml` files ONLY — never `service`,
   never `agent`, never the `version` field):
   - `description` (keep or sharpen, one line), `readme = "README.md"` ONLY if a real
     package README exists at that path — otherwise OMIT (a dangling readme breaks
     `uv build`; verify with a build, don't assume).
   - `license = "Apache-2.0"` (already present — keep), `authors`, `urls.Repository`
     (already present — keep), `classifiers` (keep; ADD `Development Status :: 4 - Beta`
     and `Intended Audience :: Developers` — state why in the PR).
   - `requires-python = ">=3.12"` (already present — keep).
   - **`dependencies` MUST be publishable:** replace every `{ workspace = true }` edge
     with a floor-pinned requirement (`turnstile-schema>=0.1.0`, etc.) that KEEPS
     resolving inside this repo (`uv sync` still green) AND resolves from PyPI after
     publish. Verify both resolvers; record the exact mechanism chosen (e.g. workspace
     for local + floor pin for publish is hatchling-incompatible — pick the real scheme
     `uv` supports and prove it both ways).
   - `[tool.hatch.build.targets.wheel] packages = [...]` already present — keep; confirm
     `uv build` emits a wheel containing exactly the package's `src/` tree (no tests,
     no fixtures leaking in — list wheel contents in the transcript).
2. **Smoke entry point** (PRD "Interfaces": "a `smoke` console entry point"):
   - ONE scheme for all 7 packages (pick the smallest that satisfies EARS #1): e.g.
     `[project.scripts] turnstile-<pkg>-smoke = "turnstile_<pkg>._smoke:main"`, where
     each `_smoke.py` imports the package, runs its cheapest real entry point
     (e.g. quality: `evaluate_quality` on a toy priced trace; schema: `load_rates` on
     the committed rates file), prints `ok <pkg> <version>`, exits 0. No network, no
     paid path, < 2 s per package.
   - New files only (`_smoke.py` per package) — NO edits to existing `src/` logic.
3. **Clean-venv harness** (`scripts/smoke_clean_venv.sh`, new): for each of the 7
   packages, in order of the dependency DAG (schema → pricing/verdict → detectors/
   replay → ingest → quality): create a temp venv (`python -m venv`, NO `--system-site-
   packages`), `pip install <wheel-or-sdist-built-from-tree>`, `import turnstile_<pkg>`,
   run its smoke command, assert exit 0. Fail-fast with the package name in the error.
   The script MUST NOT depend on `uv`, on the working tree being on `sys.path`, or on
   any dev group.
4. **Constraints.** Frozen contracts (charter §4): no `packages/schema` change, no
   pricing-formula change, no report-shape change. No engine math touched — metadata +
   new smoke shims only.

### Acceptance (dynamic, transcript required)

- `uv build` green for all 7 packages; wheel file lists attached (prove no test/fixture
  leakage).
- **Fresh-venv run:** `sh scripts/smoke_clean_venv.sh` from a machine state WITHOUT the
  repo on `PYTHONPATH` (unset it in the transcript) → all 7 imports succeed, all 7 smoke
  commands exit 0. Capture the full terminal transcript.
- `uv run pytest` (full) still green — the metadata edits did not break workspace
  resolution.
- Record the chosen `namespace` (`turnstile-<pkg>` per PRD) and confirm the 7 dist names
  match it exactly.

---

## 4. Part B — Supply-chain CI (P0 #2)

**Goal.** `pip-audit` + `bandit` + CodeQL + Dependabot wired as CI jobs with a real
threshold gate: a finding at/above threshold FAILS the release, not a warning.

**PRD refs.** Day-5 P0 #2; strict rule "a security finding at or above the release
threshold MUST block the release, not be waived"; EARS #2 (scanners gating correctly).

### Steps

1. **`.github/workflows/security.yml`** (new): two jobs, both on `push` + `pull_request`
   + `schedule: cron weekly` (state the weekday/time chosen):
   - `pip-audit`: `uv run --frozen pip-audit` (or the `pypa/gh-action-pip-audit` pinned
     action — pick one, record why). Fails the job on any `high`+.
   - `bandit`: `bandit -r packages/*/src -c <config>` with a NEW config file under
     `scripts/security/` (never inline-ignored rules in workflow YAML). Fails on
     medium+ by default (record the chosen threshold).
   - Both jobs MUST run with NO secrets in env (prove: no `secrets.*` reference in the
     file; grep transcript).
2. **`.github/workflows/codeql.yml`** (new): GitHub's `codeql-action/init` +
   `autobuild` + `analyze` for `python`, on `push` to default branch + `pull_request` +
   weekly schedule (the stock template shape — keep it stock, don't improvise). Pin
   every third-party action to a full commit SHA (supply-chain hygiene for the scanner
   itself — record the SHAs).
3. **`.github/dependabot.yml`** (new): `pip` ecosystem weekly + `github-actions`
   ecosystem weekly, both targeting the default branch, with a bounded open-PR limit
   (e.g. 5 — state the number). This is the file that will keep Part D's bumped actions
   fresh — say so in the PR.
4. **Triage + suppressions** (`scripts/security/`, new dir):
   - Run all three scanners against the CURRENT tree; triage every finding in a committed
     `TRIAGE.md`: fix the real ones in the owning file (a one-line fix in another part's
     file needs that part's session — file a follow-up, don't trespass), suppress ONLY
     with a per-finding `nosec`/`ignore` carrying a justification + expiry/review date.
     NEVER a blanket ignore (charter violation — the reviewer checks this first).
   - The release gate reads: `pip-audit`/`bandit` failures block `release.yml` (Part D
     wires `needs: [security]` — coordinate the job ID contract with Part D NOW: agree
     on job names `audit`/`bandit`/`codeql` in this session's PR description so D can
     `needs:` them without a merge race).
5. **Threshold-gate proof (MANDATORY, dynamic):** seed a KNOWN finding in a temp branch
   (e.g. a `pip-audit`-flagged pin in a scratch requirements file, or a `bandit`-flagged
   `eval()` in a scratch file — never in `src/`), push to CI, show the job FAILING;
   remove the seed, show it PASSING. Both run URLs in the transcript. This is EARS #2's
   "confirm the gate" — asserted gating is not gating.

### Acceptance (dynamic, transcript required)

- `security.yml` + `codeql.yml` + `dependabot.yml` committed; CI runs green on the tip.
- Seeded-finding FAIL transcript + clean PASS transcript (run URLs, not screenshots).
- `TRIAGE.md` lists every current finding with fix-or-justified-suppression; no blanket
   ignores (`grep -ri "nosec\|noqa\|ignore" scripts/security/` output attached).
- Full `uv run pytest` green (scanner configs changed nothing at runtime).

---

## 5. Part C — Observability: structured logging + Sentry + `/metrics` (P0 #3)

**Goal.** The service emits one structured JSON log line per request, reports unhandled
errors to Sentry (free tier, DSN-gated, inert when unset), and exposes `GET /metrics`
extending Day-3's counters — all inside the §2 budgets.

**PRD refs.** Day-5 P0 #3; "Interfaces": "`/metrics`; Sentry init behind an env DSN
(no-op when unset)"; EARS #3 (fault → log line + Sentry event), #4 (no DSN → identical
runtime); latency budget: `/metrics` < 50 ms, logging < 5 ms/request.

### Steps

1. **`observability.py`** (new, `packages/service/src/turnstile_service/`): stdlib-only
   helpers so the module imports with zero new deps:
   - `init_sentry() -> None`: reads `SENTRY_DSN` env; DSN set → `sentry_sdk.init(dsn,
     traces_sample_rate=0.0, send_default_pii=False)`; unset → no-op (MUST NOT raise,
     MUST NOT log a warning every request — one debug line at startup max). Guard the
     `import sentry_sdk` in try/except so a missing SDK ALSO degrades to no-op (belt
     and braces for the $0 path — state this in the docstring).
   - `json_log(event, **fields) -> None`: single-line JSON to the `turnstile_service`
     logger: `{ts, event, ...fields}` with NO request bodies, NO PII (call ids are
     already opaque hashes — say so; never log payload bytes).
   - `metrics_snapshot(app_state) -> dict`: reads Day-3's EXISTING counters
     (`eval_cache.stats()`, `eval_latencies` deque under its lock, `job_store` counts)
     — import nothing new, compute nothing new. This is the function both `/api/status`
     (unchanged) and the new `/metrics` render from.
2. **`app.py` wiring (minimal edits ONLY):**
   - Call `init_sentry()` once at `create_app()` top (before routes).
   - ONE http middleware (or extend the existing `cache_headers` middleware — pick ONE
     place, don't add two): per request, `t0 = perf_counter()`, after `call_next`,
     `json_log("request", method, path, status, duration_ms)`; on unhandled exception
     the existing 500 path ALSO calls `sentry_sdk.capture_exception()` guarded by
     `try/except` (observability never breaks eval — mirror the existing `# noqa:
     BLE001` pattern at `_record_eval_ms`).
   - `GET /metrics`: returns `metrics_snapshot()` as JSON (`Cache-Control: no-store`),
     response time < 50 ms (it's counter reads under one lock — assert it in the test).
     Additive-only (charter §4): no existing route's shape changes; `/api/status` bytes
     MUST be identical before/after (byte-diff test).
3. **`pyproject.toml` (service ONLY):** add `sentry-sdk>=2.0` to `dependencies` (floor
   pin, free-tier SDK). Prove `uv sync` still green AND the service boots with the SDK
   ABSENT (uninstall in a scratch venv → DSN-unset boot works — the try/except guard).
4. **`tests/test_metrics.py`** (new): `/metrics` 200 + keys match `metrics_snapshot()`;
   `/metrics` wall < 50 ms (client-measured, same style as `test_observability.py`'s
   50 ms gate); `/api/status` bytes identical to pre-change (golden the response in the
   test); logging overhead: timed double-POST shows the logging middleware adds
   < 5 ms/request MEDIAN (measure with/without via env flag or direct middleware
   bypass — record the method); fault test: force an internal 500 (monkeypatch
   `run_calls` to raise) → response is 500 AND exactly one structured log line with
   `event="request", status=500` is captured (caplog) AND (DSN set, in CI-mocked SDK
   only — never a real DSN in tests) `capture_exception` was called once.
5. **Constraints.** No Sentry DSN committed, no DSN in tests (mock the SDK object, not
   the env). `$0` default: boot + full suite with NO `SENTRY_DSN` in env — record the
   `env | grep -i sentry` empty output in the transcript.

### Acceptance (dynamic, transcript required)

- Boot with DSN unset → `/health`, `/api/evaluate`, `/api/status`, `/metrics` all 200;
  transcript shows identical evaluate bytes with/without DSN (EARS #4).
- Induced-fault run against REAL uvicorn (not TestClient): curl transcript showing the
  500, the JSON log line on stderr/stdout, and (with a throwaway DSN to a local
  request-bin OR the mocked-SDK unit proof — state which) the Sentry event captured.
- `/metrics` timing line: client-measured ms < 50; logging-overhead line: median added
  ms < 5. Full `uv run pytest` green.

---

## 6. Part D — Node-20 fix + release workflow + CHANGELOG (P0 #4, #5-partial)

**Goal.** CI off the deprecated runtime, a `release` workflow that gates on security +
tests, and a `CHANGELOG.md` skeleton ready for Part H's v0.1.0 entry.

**PRD refs.** Day-5 P0 #4 ("Fix the Node 20 CI deprecation"), P0 #5 ("v0.1.0 tag +
`CHANGELOG.md`" — scaffolding here, entry + tag in H).

### Steps

1. **`ci.yml` action bumps (EDITS to version pins ONLY — no job-logic changes):**
   - `actions/checkout@v4` → `@v5` (or current major at implementation time).
   - `astral-sh/setup-uv@v5` → `@v6` (or current major).
   - For EVERY third-party action in the file, pin to the full commit SHA alongside the
     major tag (`uses: actions/checkout@v5 # <sha>`) — record the SHAs + the date checked.
   - Prove the fix: push, show the CI run's "Runner Image / Node" lines (`ACTIONS_RUNNER_
     DEBUG` not needed — the deprecation warning line disappearing from the run log IS
     the proof; capture before/after log excerpts). If GitHub hasn't yet hard-failed
     node20, the proof is "zero deprecation warnings in the run log" — quote it.
2. **`release.yml`** (new): manual `workflow_dispatch` + `on: push: tags: ["v*"]`:
   - Jobs: `test` (same `uv run --frozen python -m pytest -q`), `security` re-run or
     `needs: [audit, bandit]` from Part B's workflow (use the job-ID contract agreed
     with Part B — if B isn't merged yet, stub with `needs: []` + a `TODO(B):` comment
     naming the exact job IDs, and H wires it finally).
   - Build wheels/sdists for the 7 libs (`uv build --package turnstile-<pkg>` × 7),
     run Part A's `smoke_clean_venv.sh` against the built artifacts (fail = no release).
   - Publish to PyPI via `pypa/gh-action-pypi-publish` with `password: ${{ secrets.
     PYPI_API_TOKEN }}` (trusted publishing if configured — record the choice); test-
     PyPI on dispatch, real PyPI on tag. NO secret echoed anywhere (grep proof).
   - Secret scan step BEFORE publish: `grep -rni "sk-\|ghp_\|pypi-\|BEGIN .*PRIVATE KEY"
     --exclude-dir=.git --exclude-dir=.venv .` must exit 1 (no hits) or the job fails.
3. **`CHANGELOG.md`** (new): `Keep a Changelog` shape with `[Unreleased]` + empty
   `## [0.1.0]` heading (Part H fills the body from the merged PRs). Seed `[Unreleased]`
   with the Day-5 entries drafted from Parts A–C PR descriptions (packaging, security
   CI, observability) — marked `(unreleased, pending H)`.
4. **`.github/workflows/link-health.yml`** (new, P1 #8 — cheap now): weekly cron reuse
   of `scripts/check_links.py` (the script `ci.yml:links` already runs) in
   non-blocking mode (`continue-on-error: true` + file an issue on failure via
   `actions/github-script`, or just log — pick one, record why). MUST NOT fail CI on a
   flaky external link (that's why it's `continue-on-error` — state this).

### Acceptance (dynamic, transcript required)

- CI run URL on the bumped `ci.yml`: green + zero node-deprecation warnings (quoted log
  lines).
- `release.yml` dry-run: `workflow_dispatch` against TestPyPI (or `--dry-run` build +
  smoke only if no TestPyPI credential exists — then it is an ENVIRONMENTAL blocker:
   record exactly which secret is missing, `PYPI_API_TOKEN` and/or `SENTRY_DSN`, and
   stop; do NOT fake a publish).
- Secret-scan step output (no hits) in the transcript. Full `uv run pytest` green.

---

## 7. Part E — Load test + GHCR image + SBOM (P1 #6, #7 — after C)

**Precondition:** Part C merged (the load target reads `/metrics` + Day-3 `/api/status`
timings; the image ships the instrumented service).

**Goal.** A documented sustained-throughput number (p95 < 300 ms) derived from measured
baselines, a GHCR-published container, and an SBOM — all free-tier.

**PRD refs.** Day-5 P1 #6 ("load test → documented limits + sustained-throughput
number"), P1 #7 ("publish the container image to GHCR; add an SBOM"); latency budget:
"sustain the throughput target at p95 < 300 ms (target set from Day-3's measured numbers)".

### Steps

1. **`scripts/load/`** (new dir, stdlib + `urllib` ONLY — no k6/locust service to host,
   no new dependency; a k6 script is accepted as an ALTERNATIVE if the author already
   has k6 locally, but the committed harness MUST run with `uv run python` and nothing
   else — record the choice):
   - `load_test.py`: boot REAL uvicorn (subprocess, like Day-3's service checks), warm
     5 requests, then N concurrent workers × M requests each against `POST
     /api/evaluate` (doc-example call, unique ids to defeat the cache for the miss
     path; then repeated ids for the hit path — report BOTH paths separately).
     Output: per-path `{rps, median_ms, p95_ms, max_ms, errors}` + the machine spec
     (reuse PERF.md's methodology header format: n, hardware, seed).
   - Target derivation (in the script's `--target` echo + the committed note): start
     from PERF.md's measured numbers + a live warm `/api/evaluate` median taken at
     runtime; the "sustained" claim = the highest RPS where p95 stays < 300 ms for a
     60-second run. Numbers go in the RUN TRANSCRIPT and `scripts/load/LIMITS.md`, NEVER
     as a code constant that CI gates on (machine-relative — CI would flake).
2. **`Dockerfile` (GHCR labels ONLY — additive):** `org.opencontainers.image.*` labels
   (title, version `$VERSION` build-arg default `0.1.0-dev`, revision `$GITHUB_SHA`).
   No base-image change, no layer reshuffle (the layer-cache comment stays valid).
3. **`.github/workflows/image.yml`** (new): on `v*` tags (+ manual dispatch): build the
   existing `Dockerfile`, push to `ghcr.io/<owner>/turnstile-demo:<tag>`, generate +
   attach an SBOM (`anchore/sbom-action` pinned to SHA — or `uv`'s SBOM if available;
   record the choice), provenance via `actions/attest-build-provenance`. NO secret in
   logs (`GITHUB_TOKEN` only — the default; a PAT is NOT needed for GHCR under the repo
   owner).
4. **Constraints.** The load harness MUST NOT run in CI as a gate (timing-flaky) — CI
   may run it in `--smoke` mode (10 requests, asserts 200s only, no timing asserts).
   The sustained number is DOCUMENTED, not gated.

### Acceptance (dynamic, transcript required)

- 60-second run transcript: RPS achieved, per-path median/p95, error count 0, machine
  spec header; the p95 < 300 ms line highlighted with the achieved RPS.
- `LIMITS.md` committed with the number + methodology + "re-run on release hardware"
  caveat.
- `image.yml` dry-run (dispatch build without push, or push to a `-dev` tag): image
  builds, SBOM artifact attached (list its first 20 lines in the transcript).
- Full `uv run pytest` green.

---

## 8. Part H — Final integration gate (sequential, end of day)

**Owner of last resort; runs after Z, A–E are all merged and green.**

1. **Version + changelog (ONLY writer):** set the 7 libraries' `version` to `0.1.0`
   (leave `agent` at its existing `0.1.0`, root + `service`/`dashboard`/others NOT
   shipped to PyPI stay `0.0.0` — record the shipped-vs-unshipped list in the PR);
   fill `CHANGELOG.md ## [0.1.0]` from the merged PR titles (packaging, security,
   observability, Node fix, load limits, calibration outcome from Z).
2. **Contract freeze check:** `git diff` over `packages/schema/**`, pricing formulas,
   and `/api/*` response shapes vs the day-start tip shows NOTHING except additive
   `/metrics` + additive log middleware (prove with the diffstat in the transcript).
3. **Full `uv run pytest` green** on the final tip.
4. **Re-run the ENTIRE Day-5 dynamic set on the final tip** (charter §3: full acceptance
   after every fix): fresh-venv install + smoke (A), seeded-finding gate FAIL→PASS (B),
   DSN-unset identical boot + induced-fault log/Sentry proof (C), node-warning-free CI
   run (D), load smoke (E), calibration report present (Z). Attach ALL transcripts.
5. **Tag + release:** push; CI green on the tip; `git tag v0.1.0` on the green commit;
   push tag → `release.yml` builds + TestPyPI smoke (real PyPI ONLY with owner approval
   — a missing `PYPI_API_TOKEN`/`SENTRY_DSN` is an ENVIRONMENTAL blocker: wire everything,
   report the missing secret by name, do NOT fake success).
6. **Reviewer checklist (Claude checks FIRST — pre-answer each item with evidence):**
   - [ ] Clean-venv install + smoke green for all 7 libs (A transcript).
   - [ ] Scanners gating correctly: seeded FAIL + clean PASS run URLs (B).
   - [ ] Observability proven by induced fault; DSN-unset path identical (C).
   - [ ] Node20 fixed: zero deprecation warnings (D run log quote).
   - [ ] v0.1.0 on a green commit; runtime contracts unchanged (diffstat).
   - [ ] $0 default path: no secret required, no paid call in CI (grep proofs).
   - [ ] CI green on the pushed tip (run URL).

---

## 9. P2 (stretch — only after every P0 gate is green)

- **Signed release:** Sigstore/cosign signing in `release.yml` (`sigstore/…` pinned
  action). Proof: `cosign verify` transcript on the published artifact.
- **Staging note:** `docs/DEPLOY.md` additive section — blue-green sketch on the
  existing Render free tier (second service + manual cutover), explicitly NOT built.

Both are MAY; neither may start while any P0 gate is red.

---

## 10. Standing rules for every session (repeat of the binding ones)

- RFC-2119 keywords; EARS checks are dynamic, named, and quantified — transcripts or it
  didn't happen.
- Fix root causes; NEVER loosen a threshold, delete a failing check, waive a security
  finding at/above threshold, or commit a secret to go green (charter violations).
- Re-run the FULL acceptance set after every fix; regressions are defects.
- Blocked at the 6-iteration cap: STOP, do not ship red; report the blocking defect
  with evidence, distinguishing *environmental* (needs a human/secret/spend: PyPI token,
  Sentry DSN, GHCR push approval) from *code* defects.
- The golden fleet headline and all pre-existing committed bytes stay identical;
  Day-5 moves NO engine math and NO committed data.
- Additive-only to shared contracts (report shape, `/api/*` + new `/metrics`, ingest
  contract, quality block, tier vocabulary). `/api/status` bytes frozen (C proves it).
- Every session ends with: `uv run pytest` green on its branch + the pushed tip's CI
  run URL in the PR description.
