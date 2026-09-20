# ISS-017: Validate fork-oracle escalation assumptions

- Status: proposed (matrix: real 0.53/0.54 both runs — the only unmapped finding voting REAL)
- Source: matrix_audit `oracleassume_real`; fork_oracle.py:44-45; METHOD.md:128-131
- Problem: ASSUME_ESCALATION_COMMITS / FORKED_MUTATION_ATTEMPT defaults unvalidated
  open-loop; enriched 13/13 undecidable.
- Proposal: open-loop measurement or explicit assumption registry with per-case flags.
- Accept when: assumptions measured, or each default carries evidence + a re-check date.
