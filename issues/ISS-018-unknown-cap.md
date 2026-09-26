# ISS-018: Split the reused unknown-cap 0.6

- Status: implemented (PR pending review)
- Source: matrix_audit `unknowncap_*`; adjudicate.py:93,265-287,475-489
- Problem: one 0.6 cap covers two distinct ambiguities (unknown effect vs informational
  timeout/error/hangup); turn_of_no_return inconsistent (u_turn vs None).
- Proposal: separate caps + consistent turn_of_no_return, or documented reason to share.
- Accept when: distinct handling pinned by fixtures, or sharing justified in comment + docs.

## Resolution

Split into two named constants with the SAME value 0.60 (new names
`UNKNOWN_EFFECT_CONFIDENCE_CAP`, `NON_CLEAN_END_CONFIDENCE_CAP` in
`packages/verdict/src/turnstile_verdict/adjudicate.py`); the old
`UNKNOWN_CONFIDENCE_CAP` stays as a backward-compatible alias. No calibration
data justifies different values, so the values are shared on purpose until
ISS-001 tunes each independently; the separate names are what make that
tuning possible without another rename.

`turn_of_no_return` behavior kept as-is and documented (PRD section 7 rule,
"the earliest turn at which the final verdict was already determined"):

- unknown effect: the verdict is fixed the moment the ambiguous mutation
  happens, so `turn_of_no_return = u_turn` is right.
- non-clean end (timeout / error / agent_hangup on the informational path):
  the conversation never reached a determining turn; the call was cut off by
  something outside the dialogue, so `turn_of_no_return = None` is right.
  Contrast ABANDONED, where the caller's own hangup turn IS the determining
  event.

No verdict label, confidence value, evidence dict, or `turn_of_no_return`
value changed (naming and documentation only). Tests pin the split: distinct
names + shared value, fixture-20 turn rule, non-clean-end `None` rule, and a
monkeypatch test proving the branches read different constants. METHOD.md
"Modeling choices, stated" documents both caps and both rules.
