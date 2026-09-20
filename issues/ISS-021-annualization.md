# ISS-021: Margin annualization honesty

- Status: proposed (matrix: needs-evidence 0.74/0.74 — investigate, don't claim)
- Source: matrix_audit `annualize_*`; margin.py:82-88
- Problem: linear annualization with max-n reference can flatter the margin %;
  measurable-subset denominator excludes inferred calls.
- Proposal: disclose annualization assumptions beside every annualized figure, or drop it.
- Accept when: every annualized number carries its assumptions, or annualization removed.
