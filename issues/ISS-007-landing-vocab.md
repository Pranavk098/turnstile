# ISS-007: Generated landing numbers + unified label vocab

- Status: proposed
- Source: c2_hygiene (`full 0.87, review`); Track B vocab drift
- Problem: `home.html:111-125` hardcodes 1.32%/4.1% (drifts on regen); UI says
  Proven/Measured/Conditional, docs say Measured/Instrumented/Not-yet-measured,
  code says tier1_measured/tier2_modeled.
- Jev verdict: full guards over minimal — generate, unify, CI-guard.
- Proposal: landing numbers generated from pipeline; one vocab map; regen-stability test.
- Accept when: regen produces identical-or-stamped numbers; single vocab everywhere.
