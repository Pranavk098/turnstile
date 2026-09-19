# ISS-003: Fix per-turn attribution (tokens + telephony)

- Status: proposed
- Source: ingest_audit (even-split fairness only 0.40); Track C future-item 6
- Problem: call-level tokens even-split flattens D2 slope by design; telephony
  pro-rata misattributes short/long turns (`vapi.py:322-333`; `pricing.py:144-149`).
- Jev verdict: ABSENT-omit backed (0.81), but even-split doubted — attribution is the gap.
- Proposal: text/time-proportional split, or activity-union attribution per the D8 rule;
  disclose the method on every surface.
- Accept when: golden diff shows fair per-turn split; method disclosed in INGEST.md.
