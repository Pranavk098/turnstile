# Security triage — Day-5 Part B (supply-chain CI)

Scanned 2026-09-18 (bandit 1.9.4, pip-audit 2.10.1) against the working tree.
Gate: pip-audit fails on ANY known vuln (subsumes high+); bandit fails on
medium+ (`--severity-level medium`). CodeQL runs in CI only (no local runner).

## Verdict: NO finding at/above threshold. Gate is GREEN, zero suppressions.

- `pip-audit`: **clean** — "No known vulnerabilities found" (exit 0). The 12
  `turnstile-*` workspace packages report "not found on PyPI, could not be
  audited" — expected pre-publish (Part A/H), not a finding.
- `bandit` over `packages` at medium+: **0 issues** (exit 0).
- `bandit` all-severities: only LOWs (22 in `*/src`, all Low; 2551 outside
  `*/src` — 2544x B101 `assert` in tests plus 7 other lows, incl. B404/B603 in
  `agent/spikes/playback_probe.py` and one B105 `'1'` false positive in a test
  file). Lows are below the release threshold: accepted as-is, no `nosec`, no config skip. Revisit only if a
  finding is re-graded to medium+ upstream.
- `CodeQL`: no local run possible; verdict comes from the first CI run after
  merge (push from this environment is blocked: the `pranavk-4` credential
  gets HTTP 403 on push to Pranavk098/turnstile -- read-only token. The owner
  MUST confirm the codeql job green on the merge commit).
- Threshold-gate proof: done LOCALLY (CI push blocked, see above). Seeded
  `eval()` in `packages/_gate_seed_bandit.py` (temp file, since deleted) →
  `bandit ... --severity-level medium` exits 1 with B307 on the seed (FAIL);
  seed removed → exit 0, "No issues identified" (PASS). Transcripts:
  local FAIL/PASS logs retained alongside this session's report.

## Per-finding notes (src scope — all Severity: Low, all below threshold)

| # | ID | File (owner) | Note |
|---|---|---|---|
| 1 | B101 assert | `detectors/.../_smoke.py`, `ingest/.../_smoke.py`, `pricing/.../_smoke.py`, `quality/.../_smoke.py`, `replay/.../_smoke.py`, `schema/.../_smoke.py`, `verdict/.../_smoke.py` (Part A WIP) | Smoke shims asserting cheap invariants; correct use, below threshold. Follow-up for Part A: none required. |
| 2 | B101 assert | `experiments/.../preservation_divergence.py:101`, `quality/.../__main__.py:107` | Internal sanity asserts, not security boundaries. No action. |
| 3 | B404/B607/B603 subprocess | `experiments/.../manifest.py:15,25`, `service/.../app.py:29,107` (Part C) | Fixed-argv `git rev-parse` calls, `shell=False`, wrapped in try/except. No untrusted input reaches the command line. Below threshold; follow-up for Part C: consider absolute git path if ever run under attacker-controlled PATH — informational only, NOT requested as a fix. |
| 4 | B105 hardcoded-password (FALSE POSITIVE) | `ingest/.../providers/retell.py:1009` | Matched the English log string "tokens: no agent turns carry LLM telemetry". Not a credential. No action. |
| 5 | B105 hardcoded-password (FALSE POSITIVE) | `quality/.../calibration_study.py:55` (`'pass'`) | Matched the literal word `pass` (calibration label value). Not a credential. No action. |
| 6 | B311 random | `live/.../bargein.py:62,226` | Simulation jitter for the barge-in harness, not cryptographic use. No action. |
| 7 | B110 try/except/pass | `service/.../app.py:352`, `service/.../observability.py:54` (Part C) | Deliberate "observability never breaks eval" pattern, already documented inline (`# noqa: BLE001`). No action. |
| 8 | B101 assert (bulk) | all `packages/*/tests/**`, `packages/agent/spikes/**` | Standard pytest asserts + spike scripts. Below threshold by category; not enumerated line-by-line. No action. |

## Fixes / suppressions applied by Part B

NONE. No finding was at/above threshold; nothing in Part B's owned files
(CI YAML, this dir) was flagged; other parts' files were not touched.
`grep -ri "nosec\|noqa\|ignore" scripts/security/` returns only this file's
prose mention of the policy (no active suppression).

## Suppression policy (binding on future edits)

Suppress ONLY per-finding with justification + review date, e.g.
`subprocess.run(...)  # nosec B603 -- fixed argv, shell=False; review 2027-01`.
NEVER a blanket `skips:` entry in `bandit.yaml` or an inline rule-disable in
workflow YAML (charter violation: fixing the gate, not the cause).
