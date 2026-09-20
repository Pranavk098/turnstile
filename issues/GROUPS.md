# Three working groups — build order for ISS-001..021

Shared testing doctrine for every issue: golden fixtures first, unit + regression tests,
regen determinism (same seed → byte-identical), Jev re-vote on the same decision key
pre/post fix (celesto-style: the fix must move the vote, or the fix is wrong), and a
final honesty-label check. Nothing merges with a bare point estimate or an unstamped number.

## Group A — Trust surfaces & gates (ISS-006, 007, 008, 010, 021)

Objective: every number shown is stamped, labeled, reproducible; paid paths fail closed.
All $0. Ship first — unblocks honest claims for everything else.

Sequence:
1. **ISS-010 decision** (human call, Jev is 0.67 unknown): **DECIDED 2026-09-20 → force-ABSENT**
   (gated on G1 concurrency redesign). Recorded in the issue; implementation is a follow-up.
2. **ISS-008** — inline (n, dataset) stamps on all headlines + stale-number sweep
   (README measured-at-scale, home 4.1%, index n=150, DEMO 750).
   Test: grep-guard script failing on bare headlines; Jev re-vote `c2_readme_stamp` → act.
3. **ISS-007 + ISS-021 together** — landing numbers generated from pipeline, one vocab map,
   annualization assumptions disclosed beside every annualized figure.
   Test: regen-stability (two regens byte-identical or diff stamped); re-vote `c2_hygiene`.
4. **ISS-006** — paid check moves to submit (422/500, never 202) + audit trail.
   Test: ALLOW_PAID=1 + paid backend → submit rejected; re-vote `service_audit` → act.

Group acceptance: regen test green, headline guard green, paid-submit test green,
all four re-votes at review-gate or better.

## Group B — Pipeline correctness (ISS-001, 002, 003, 004, 005, 009, 011, 017, 018, 019, 020)

Objective: the numbers Jev already backs get earned — measured, attributed, calibrated.
Phased inside the group; do not skip phases.

- **B1 money math first** (everything prices off this): ISS-011 dated vendor rows +
  manifest → ISS-003 proportional/union attribution → ISS-002 turn-partial coverage.
  Test each against goldens + `test_pricing`/`test_vapi` suites; re-vote
  `schema_pricing`, `c2_ingest_partial`.
- **B2 verdict**: ISS-009 binding-edge fixtures → ISS-018 split caps → ISS-017 oracle
  assumptions measured or registered. Re-vote `verdict_v2` / `verdict_audit` →
  act with dissent < 0.1.
- **B3 margin honesty**: ISS-004 real-usage companion beside CR-B; METHOD.md updated.
  Re-vote `c2_chunk_gate` — either side may win, but confidence must clear review.
- **B4 detectors + agent**: ISS-020 UNKNOWN-BASELINE signal → ISS-019 single synthesis →
  ISS-005 clause default + local-only label → ISS-001 scaffolding now (sweep harness +
  report format), tuning deferred to first real fleet (blocked on ISS-012).
  Re-vote `c2_ship_default`, `detectors_v2` (unknown must resolve to a real option).

Group acceptance: full `pytest` green, no new UNVERIFIED claims without an issue link,
matrix re-run shows zero REAL-unmapped findings.

## Group C — Capability unlocks (ISS-012, 013, 014, 015, 016)

Objective: new measurement powers, in dependency order. ISS-016 may parallelize anytime.

1. **ISS-012 real-fleet adapter** — unblocks ISS-001 tuning and all fleet-scale claims.
2. **ISS-013 kappa study** — 60 hand labels → report → open judges only at κ≥0.75.
3. **ISS-014 open-loop preservation** — n=72→200 with Wilson CIs; answers "is cheaper safe?".
4. **ISS-015 replay-executable remedies** — graduates through §8.3 or stays conditional.
5. **ISS-016 perf + publish** — bench, pip install, deploy docs.

Group acceptance: each graduates by its own Accept-when boxes; no conditional result
presented as proven at any point (ISS-008 guards apply here too).
