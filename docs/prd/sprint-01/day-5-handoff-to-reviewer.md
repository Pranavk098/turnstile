# Day-5 handoff to reviewer (Claude) — analyze, then push to remote

**Branch:** `day5-implementation` (cut from `day5-part-d` @ `fdfd09b`, base `dad2af2` = Day-3 tip).
**Working tree:** clean. **Nothing pushed** — push + CI confirmation is YOUR job (see §7).
**Test state at handoff:** full `uv run python -m pytest -q` → all green EXCEPT 1 known red:
`tests/test_readme_count.py::test_readme_suite_count_matches` (README.md:37 still says
"1191 passed, 4 skipped"; tree now collects ~1255+ after new test files — refresh the
count at integration, do NOT delete the guard).

> Note: in this environment the bare `uv run pytest` shim is blocked by App Control
> (OS error 4551); the canonical equivalent used throughout is
> `uv run python -m pytest -q` (same suite, CI form).

## 1. Commit inventory (review in this order)

| # | SHA (short) | Message | Contents |
|---|---|---|---|
| 0 | `a99dc94` | ci(release): Day-5 Part D | `ci.yml` pin-only bumps, NEW `release.yml`, `CHANGELOG.md`, `link-health.yml` (pre-existing on branch) |
| 0 | `971683e`, `79ec65a` | release secret-scan fix; setup-uv v10.1.0 | Part D fixes (pre-existing) |
| 0 | `fdfd09b` | docs(issues): Jev backlog ISS-001..016 | Other track, pre-existing — not yours to review deeply, just note it |
| 1 | `b0185b0` | feat(quality): Day-4 … honest shortfall report | 22 files: `fixtures/calibration/` (selection.json, labels.jsonl 120 rows, reference_log.jsonl, **calibration_report.json**), `labeling.py`, `__main__.py`, `calibration_study.py` + tests, adapter.py mod, `test_truncated_by.py`, `test_bargein.py` mod, `INGEST.md` mod, `test_gate_dynamic.py`, `test_quality_gate_wire.py`, `bench_quality.py`, `reference_label.py`, `test_ci_perf_gate.py`, Makefile/PERF.md/README.md/test_observability.py mods |
| 2 | `a2b486b` | feat(packaging): Day-5 Part A | 7 lib `pyproject.toml` metadata (NOT versions), 7× `_smoke.py` (new shims, zero src edits), `scripts/smoke_clean_venv.sh` |
| 3 | `085b28e` | ci(security): Day-5 Part B | NEW `security.yml` (jobs `audit`+`bandit`), `codeql.yml` (job `codeql`), `dependabot.yml`, `scripts/security/bandit.yaml` + `TRIAGE.md` |
| 4 | `fd2513b` | feat(service): Day-5 Part C | NEW `observability.py`, `app.py` wiring, service `pyproject.toml` (+`sentry-sdk>=2.0`), NEW `test_metrics.py` (5 tests), `uv.lock` (+sentry-sdk 2.69.2) |
| 5 | `41b8d33` | feat(release): Day-5 Part E | NEW `scripts/load/load_test.py` + `LIMITS.md`, `Dockerfile` +9 label lines, NEW `image.yml` |
| 6 | `b0ab715` | docs(issues): ISS-017..021 | Other track — note only |
| 7 | `df66090` | docs(prd): work-split plans | `day-4-work-split.md`, `day-5-work-split.md` — the specs everything was built against |

Specs: `docs/prd/sprint-01/00-charter.md` (binding), `day-5-harden-package.md`,
`day-5-work-split.md`, `day-4-work-split.md`, `day-4-quality-calibrated.md`.

## 2. What was proven (evidence claimed by implementing sessions — VERIFY)

- **Day-4 Z:** `calibration_report.json` exists but declares an **honest shortfall**:
  every label row has `human_label: null` → n=0/dim, `passes_gate: false`, gate closed,
  Part F (judges) MUST NOT start. Re-derivation byte-identical. Quality suite 87 passed.
  **The unblocking act is a human rater session** (Part A CLI over 60 calls), not code.
- **A:** `uv build` × 7 clean (wheel = src tree only); **all 7 clean-venv smokes exit 0**
  with repo off `sys.path`. Deps scheme: floor pins (`>=0.0.0`) for pip + retained
  `{workspace=true}` for uv; `uv sync --frozen` green, zero lock churn from A.
  **Known debt (in-shim, unfixed):** `detectors`/`replay` load `pricing/rates.yaml`
  CWD-relative — real `detect()`/`replay()` on non-empty traces still needs a checkout;
  needs `importlib.resources`/package-data follow-up by owning session.
  Floor pins should tighten to `>=0.1.0` alongside the H version bump.
- **B:** pip-audit clean; bandit medium+ 0 issues; zero suppressions. Gate proven
  LOCALLY (seeded `eval()` → exit 1; removed → exit 0). **No CI run URLs — push got
  403 (read-only token).** Release-gate contract for `release.yml`: `needs:
  [audit, bandit, codeql]` (currently stubbed as `TODO(B)` — wire it).
- **C:** `/metrics` 2.4 ms (TestClient) / 4.5–20 ms live (budget 50 ms); logging
  overhead 0.13 ms median (budget 5 ms); forced-500 → exactly one JSON log line +
  mocked `capture_exception` × 1; DSN-unset vs throwaway-DSN evaluate bytes
  sha256-identical (`12a01eec…98ccb`). `/api/status` bytes frozen; `cache.py`/`jobs.py`
  zero diff. Service suite 89 passed.
- **D:** `checkout@v5` + `setup-uv@v10.1.0` (**deviation with runner-log proof:**
  `@v6` still targets node20). After-run log has zero node-deprecation matches.
  Release dry-run stops exactly at the credential boundary (`PYPI_API_TOKEN` absent —
  environmental). link-health dispatch green. Base PR #1 needs owner Approve click.
- **E:** sustained **9.6 RPS @ p95 249 ms** (miss path, 60.2 s, n=577, 0 errors);
  hit path 533 RPS / p95 32 ms. `docker build` + OCI labels + `/health`+`/metrics`
  200 from container + syft SBOM (SPDX, 681 pkgs) proven locally. GHCR push +
  attestation pending a privileged runner invocation.

## 3. Fresh verification REQUIRED (do not trust §2 on assertion)

1. `uv run python -m pytest -q` on the tip; only acceptable red is the README-count
   guard (then fix the count: run suite, write `N passed, M skipped` into README:37).
2. `sh scripts/smoke_clean_venv.sh` (needs POSIX sh + network for pip; Git Bash OK).
3. Re-run `scripts/load/load_test.py --smoke` (timing asserts must NOT exist in smoke).
4. `git diff dad2af2..HEAD -- packages/schema/ pricing-formulas /api/*` — expect ONLY
   additive `/metrics` + log middleware; golden headline byte-identical.
5. Confirm `calibration.py` untouched (`git diff` empty) and no secret committed
   (re-run the `release.yml` secret-scan grep).
6. Flake watch: `test_logging_overhead_median_under_5ms` failed twice under parallel-
   session load (6.07/6.46 ms), passes on quiet tip — re-run on quiet machine before
   judging it.

## 4. Reviewer gates (day-PRD + charter — check FIRST)

- [ ] No uncalibrated score can reach headline/beside-cost (coax transcripts in code:
  `test_gate_dynamic.py`, `test_quality_gate_wire.py` — re-run, don't eyeball).
- [ ] Clean-venv install + smoke green (re-run harness).
- [ ] Scanners gating correctly — **still needs CI run URLs** (push was 403 here).
- [ ] Observability proven by induced fault; DSN-unset identical (re-run live proof).
- [ ] Node20 fixed (quote the after-run log).
- [ ] $0 default path (no secret required; no paid call in CI — grep).
- [ ] Runtime contracts unchanged (diffstat proof).

## 5. Known issues to resolve (not defects in the parts — integration work)

1. README suite count stale → refresh at integration (this unblocks the 1 red test).
2. `release.yml` still has `TODO(B)`/`TODO(A)` stubs → wire `needs: [audit, bandit,
   codeql]` now that B exists; point smoke step at committed `smoke_clean_venv.sh`.
3. Floor pins `>=0.0.0` → tighten to `>=0.1.0` when bumping versions.
4. `detectors`/`replay` rates.yaml CWD-relative debt (see §2-A).
5. `test_logging_overhead` flake characterization (see §3.6).

## 6. Explicitly OUT for this review (do not expand scope)

Part H (version bumps → `0.1.0`, tag, real publish) is NOT done — versions intentionally
left at `0.0.0`. P2 (Sigstore signing, staging note), Day-4 F (judges — blocked on
κ ≥ 0.75 + human labels), Day-4 G (docs surfacing) are declined/deferred, not missing.

## 7. Your push job (owner has granted rights for this step)

1. Push `day5-implementation` to remote (origin was 403 with the prior token — use the
   credential provided for this session; do NOT commit secrets to achieve it).
2. Confirm CI green on the pushed tip; attach run URLs to your report. If B's
   `security`/`codeql` jobs or any job is red, fix forward on the branch (small,
   scoped commits) — do NOT loosen thresholds, delete checks, or waive findings.
3. Open (or update) the PR against the default branch with: per-commit summary, §4
   checklist pre-answered with evidence, remaining environmentals (`PYPI_API_TOKEN`,
   `SENTRY_DSN`, human-rater session, GHCR/tag-run approval).
4. Report back: what you verified vs trusted, every defect found with file:line, and
   anything you changed after this handoff.
