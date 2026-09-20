# ISS-018: Split the reused unknown-cap 0.6

- Status: proposed (matrix: needs-evidence, fix-now leads 0.42 both runs)
- Source: matrix_audit `unknowncap_*`; adjudicate.py:93,265-287,475-489
- Problem: one 0.6 cap covers two distinct ambiguities (unknown effect vs informational
  timeout/error/hangup); turn_of_no_return inconsistent (u_turn vs None).
- Proposal: separate caps + consistent turn_of_no_return, or documented reason to share.
- Accept when: distinct handling pinned by fixtures, or sharing justified in comment + docs.
