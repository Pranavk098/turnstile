# ISS-020: D4 silent-no-baseline signal

- Status: proposed (matrix: needs-evidence 0.63/0.65; D2 priors stay under ISS-001)
- Source: matrix_audit `d4silent_*`, `d2prior_*`; d04:33-36
- Problem: D4 goes silent when a scenario has no baseline — missed waste with no signal;
  D2 first-turn baseline + slope/cache priors uncalibrated (folded into ISS-001).
- Proposal: explicit UNKNOWN-BASELINE finding instead of silence, so absence is visible.
- Accept when: no-baseline scenarios emit a labeled finding; goldens pin it.
