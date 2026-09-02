# GLM brief — sweep the buffer-lead policy (lead_cap) for the barge-in number

**Fast follow to `opencode/barge-in-number` (merged @ 5917118).** ~1 hour. Branch
`opencode/leadcap-sweep` off `wave0-foundation`.

## Why
The barge-in waste magnitude is driven by the streaming **buffer-lead policy**
(`sim.DEFAULT_LEAD_CAP_S = 2.0`), NOT the ~40× generation rate (40× is just why
generation wins the race; with a bounded buffer the waste is ~insensitive to raw
speed). Today the report sweeps the barge-in RATE but holds `lead_cap` fixed at
2.0s — so the single load-bearing parameter the number scales with is unswept.
A voice CTO's first question is "why 2 seconds?". Sweeping it turns that question
into the FDE hook ("here's waste vs. buffer policy — what's yours?") and completes
the honesty exhibit.

## What to build
- Add a **lead_cap sweep** to `bargein_report` (a second 1-D sweep, alongside the
  existing rate sweep): hold the barge-in rate fixed at the cited **0.15** default,
  vary `lead_cap_s` over a **stated plausible range of streaming buffer policies**,
  suggested `[0.5, 1.0, 2.0, 3.0, 4.0]` seconds. Emit a table:
  `lead_cap_s → D7 $ · $/call · % of TTS spend · [bootstrap CI]`.
- **Reuse the SAME measured phase-1 schedules** across lead_cap points — `lead_cap`
  only affects the phase-2 replay (`generate_ahead`'s cap), never the measured
  chunk schedule. So measure each call's schedule ONCE and replay it at every
  lead_cap value: the anti-tuning guarantee is preserved and the sweep is cheap.
- **Provenance/label** (same rule as the rate sweep): the buffer-lead range is a
  **stated plausible policy band, not a claim about any vendor's pipeline**; the
  measured quantity underneath (generation-ahead behavior, chars generated-vs-heard)
  is real. Do NOT pick a range that flatters the 2.0s point — center it plausibly.
- Keep the existing rate sweep exactly as is (at fixed lead_cap = 2.0s). Both 1-D
  sweeps ship in the same `bargein_report.json`.

## Acceptance
- New lead_cap sweep table in the report + CLI, **monotonic** (more buffer → more
  waste), each point with a bootstrap CI, at fixed rate 0.15.
- A test asserting monotonicity in `lead_cap` and that lead_cap does not alter the
  measured phase-1 schedule (same `intended_chars`/`total_audio_s` across points).
- Suite green, `ruff check packages/` clean. Boundary: `packages/agent` +
  `packages/experiments` only; no schema/fixtures.

## Out of scope
A full 2-D (rate × lead_cap) grid — two independent 1-D sweeps are cleaner for the
demo. Real buffer-policy citations (none clean exist; the stated-band label is the
honest treatment).
