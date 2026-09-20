# ISS-007: Generated landing numbers + unified label vocab

- Status: half-done 2026-09-20 (landing: already guarded — see below; vocab: documented)
- Landing finding: `test_home_numbers_match_the_pipeline_output` already pins home.html
  numbers to pipeline JSON — hardcode + pinning test is the design, regen drift fails
  loudly instead of lying. No change needed.
- Vocab finding: UI chips vs quality `Tier` are different axes (claim tiers vs scoring
  tiers, verified in `types.py:6-12` + `index.html:449`) — merged table would lie.
  METHOD.md now carries the do-not-conflate note. Full rename out of scope.
