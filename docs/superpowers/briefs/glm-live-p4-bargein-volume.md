# Brief — Live agent Phase 4: barge-in at volume (the real D7/D8 headline)

**Base:** `wave0-foundation` @ `fbed5e7`. Branch `opencode/live-p4-bargein-volume`.
Reviewed + merged by Claude. **Owner-gated paid, budget-capped $2. Build TDD.**

## Goal
Upgrade the barge-in headline from "measured on a TTS harness (modeled 15% rate)" to
"**measured across 100–200 full live conversations with a caller who actually interrupts.**"
This is the number a voice-AI CTO checks against his own intuition, and it's the project's
one vendor-unique differentiator. Measure D7 (barge-in waste) and the acoustic classes D6/D8
end to end, at volume, on real Piper audio.

## Mechanism
1. **A synthetic interruption-heavy caller** (new module, e.g. `packages/live/.../caller.py`):
   generates the next caller utterance AND decides whether it **barges in** during the
   agent's TTS playback, and at what position. Give it a per-turn barge-in probability and an
   interruption-position distribution — **swept, not a single tuned value** (report the
   sweep). Make it interruption-heavy (the proposal's "impatient caller").
2. **Full live loop, at volume:** reuse the Phase-2 voice loop (local Whisper STT + reused
   Piper TTS via the harness by import + capped `gpt-5-mini` policy in the free bucket +
   mock tools). Run **100–200 conversations** on ONE interruption-heavy scenario. When the
   caller barges in mid-utterance, `chars_played` < `chars_synthesized` — that gap, priced,
   is D7.
3. **Measure + aggregate on the real audio:** D7 (synthesized−played, per the G2 fields —
   NEVER `len(text)`), D6 (dead tokens), D8 (silence tax), across the run. Report D7 as a %
   of TTS spend with its CI and the barge-in-rate sweep, alongside the existing ~4% Piper
   number for comparison.

## Boundaries (hard)
- `packages/live/` only. Reuse `turnstile_agent`'s Piper by import — **NEVER edit the
  barge-in harness**, `packages/schema`, `fixtures/golden`, `docs/METHOD.md`,
  `docs/LIMITATIONS.md`. Claude lands the headline in METHOD.
- Local Whisper/Piper are free; the LLM stays in the free bucket via
  `TURNSTILE_PAID_MODEL_CAP=gpt-5-mini`. **Owner-gated paid, STOP if estimate > $2.**
- **Runtime guard:** 100–200 full acoustic calls is compute-heavy (Whisper+Piper). If a full
  200-call run would take hours, START at 50, report, and flag — do not silently run for
  hours. Make n a CLI arg.
- Acoustic honesty is load-bearing: `chars_synthesized`/`chars_played` come from the real
  Piper accounting + the actual interruption position, never `len(text)`. G2 (docs/GATES.md).
- TDD the caller (interruption sampling is deterministic under a seed) and the D7 aggregation
  (interruption-position → chars_played → priced waste). Green + `ruff check packages/` clean.

## Acceptance
- 100–200 (or the runtime-capped n) full live calls run on an interruption-heavy scenario;
  D7/D6/D8 measured **on the real audio**, at volume, with a barge-in-rate sweep + CI.
- The D7 headline reported as a % of TTS spend, compared to the ~4% harness figure, honestly
  (real interruption behavior vs the old modeled 15% rate).
- Determinism under a seed (tested); acoustic fields from real accounting, never `len(text)`.
- `packages/live/` only; harness/schema/golden/METHOD untouched; suite green; ruff clean;
  spend ≤ $2 reported.
- Delivery report: the measured D7 (+ sweep), n, actual spend, runtime, and 2–3 example calls
  (what the caller interrupted, how much audio was billed-but-unheard).
