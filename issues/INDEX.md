# Active issues — Jev-audited, human-decided

Every issue below came from the Cycle-1/2/3 audits (8 section explorers, 3 improvement
tracks, 16 live `jev-1.13.0` votes; records in `scripts/jev_decide.py`, rerun with
`python scripts/jev_decide.py --decision <key>`). Jev votes; humans merge.

Statuses: `accepted` (Jev act-gate) · `proposed` (review-gate or agent-flagged) ·
`contested` (escalate — needs a human call) · `future` (planned, policy-held).

| ID | Title | Status | Re-vote key |
|----|-------|--------|-------------|
| ISS-001 | Tune detector thresholds on real traffic | accepted | c2_thresholds |
| ISS-002 | Turn-level partial ingest coverage | accepted | c2_ingest_partial |
| ISS-003 | Fix per-turn attribution (tokens + telephony) | proposed | ingest_audit |
| ISS-004 | Gate remedy claims on real-usage delta | contested | c2_chunk_gate |
| ISS-005 | Clause default + local-only barge-in label | proposed | c2_ship_default |
| ISS-006 | Fail-closed paid gate at submit time | proposed | service_audit |
| ISS-007 | Generated landing numbers + unified label vocab | proposed | c2_hygiene |
| ISS-008 | README stamp + stale-number sweep | proposed | c2_readme_stamp |
| ISS-009 | Verdict binding edge-case review | contested | verdict_audit |
| ISS-010 | Live D8 policy: force-ABSENT vs Tier-2 tag | contested | c2_d8_absent |
| ISS-011 | Pricing placeholders + rate-table staleness | proposed | schema_pricing |
| ISS-012 | Real-fleet adapter (second provider) | future | — |
| ISS-013 | 60-label kappa study, then open judges | future | c2_ship_judges |
| ISS-014 | Open-loop preservation at scale | future | replay_audit |
| ISS-015 | Replay-executable remedies (conditional → proven) | future | — |
| ISS-016 | Perf baseline + publish (bench, pip, deploy) | future | — |
| ISS-017 | Validate fork-oracle escalation assumptions | proposed | matrix_audit |
| ISS-018 | Split the reused unknown-cap 0.6 | proposed | matrix_audit |
| ISS-019 | Remove PiperTts double synthesis | proposed | matrix_audit |
| ISS-020 | D4 silent-no-baseline signal | proposed | matrix_audit |
| ISS-021 | Margin annualization honesty | proposed | matrix_audit |

Rule: closing an issue means its Accept-when boxes are ticked in code/tests/docs,
not that Jev once voted for it.
