# ISS-008: README stamp + stale-number sweep

- Status: proposed
- Source: c2_readme_stamp (0.71); Track B honesty audit
- Problem: headline 0.57% quoted without inline (n=250, seed 0); stale surfaces —
  README "measured at scale" vs small-n LIMITATIONS; home 4.1% vs METHOD 12.1%/28.7%;
  index n=150 vs METHOD n=200; DEMO 750 calls.
- Jev verdict: stamp inline; footnote alone insufficient.
- Proposal: inline (n, dataset) on every headline + one stale-number sweep ($0).
- Accept when: every headline stamped; sweep diff reviewed; CI count-guard (see ISS-007).
