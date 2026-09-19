# ISS-001: Tune detector thresholds on real traffic

- Status: accepted
- Source: c2_thresholds (`tuned 0.98, conf 0.96, act`); c1 detectors (`other 0.50, escalate, risk 1.43`)
- Problem: D1 32-tok, D2 slope>400+cache<0.5, D3 cosine 0.85, D8 200ms are PRD-verbatim,
  synthetic-only. D2/D6 never fire on the 250-corpus (`d01:33; d02:26-27; d03:61; d08:43`).
- Jev verdict: tune, overwhelmingly. Twist: synthetic-tuned-transfers scored only 0.25 —
  tune on REAL traffic, never on the corpus.
- Proposal: per-detector ROC/sweep on first real fleet + CIs + calibration report checked in.
- Accept when: report exists; thresholds pinned with tests; D2/D6 either fire or are
  documented-absent with reason.
