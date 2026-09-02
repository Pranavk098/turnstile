# GLM brief — the measured barge-in waste number (D7 Tier-2 → Tier-1 headline)

**Goal:** produce ONE real, dollar-signed number nobody has published — *the % of
TTS spend synthesized-and-billed but never heard, because a streaming TTS
generates ahead of playback and the caller barges in* — as the demo headline,
replacing the deterministic 0.57%. **1-week deadline.**

**NO WSL2. NO Pipecat. NO telephony. NO real-time ASR/LLM.** The measurement is
TTS→playback character accounting over a timeline; the Wave-0 spike
(`packages/agent/spikes/playback_probe.py`, kill-check PASSED) already proved it
runs natively on Windows with real Piper, no audio device. Extend that spike into
a real harness — do not build a conversational voice stack.

## Lane boundaries
GLM owns `packages/agent/` (promote from spike to a real module) and may add a
thin driver in `packages/experiments/`. **Do NOT touch `packages/schema/` or
`fixtures/golden/`.** Route every trace through the existing G1 `TraceRecorder`
(`packages/otel`) — do not invent a new trace shape. Claude reviews + merges. Ends
green + `ruff check packages/` clean.

## What to build

1. **Native barge-in harness** (`packages/agent/`, from the spike):
   - Real Piper TTS (native Windows), streaming model: generation stays
     ~`GEN_LEAD` audio-seconds ahead of playback (measure Piper's *actual* lead,
     don't assume — this real generation-ahead behavior is the novel part).
   - **G2 preserved:** emit `tts.synthesize.chars_synthesized = GENERATED/billed`
     (never intended, never `len(text)`), via `record_tts`; emit the matching
     `audio.playback` span (`chars_played = heard`). Use `at_ms`/`into_previous_ms`
     so playback overlaps synthesis (this is *why* G1 landed).
2. **Scenario = long confirmation readback** (where barge-in waste concentrates):
   a handful of realistic agent readback utterances ("Let me confirm your order:
   … total $W, correct?"). Author 5–10 (GLM drafts, Claude reviews) — these are
   agent scripts, not the measurement, so low-stakes; they must be *realistic*, not
   length-tuned to inflate waste.
3. **Barge-in driver — modeled, cited, NOT tuned:** sample whether the caller
   barges in (rate) and WHERE in the readback (position) from cited distributions
   (reuse `turnstile_corpus.distributions.BARGE_IN_RATE` provenance; cite the
   position model). On barge-in, cancel further synthesis. **Report as a sweep over
   the barge-in rate** (like the existing D7 sweep), never a single asserted figure.
4. **Pipe through the built instrument, unchanged:** each "call" → `TraceRecorder`
   → `Trace` → `price_trace` → `detect` (D7) → `aggregate`. Run **N = 100–200
   calls**. Output: D7 waste in **$ and as % of TTS spend**, with a bootstrap CI
   and the rate sweep.

## Honesty guardrail (non-negotiable — this is the whole point of the pivot)
The output provenance string MUST say, in plain words: *real Piper TTS
generation-ahead behavior, measured; barge-in rate and position modeled from cited
distributions and swept; N controlled harness calls, not production traffic.* The
real, novel quantity is the **TTS generation-ahead waste per barge-in** (nobody has
measured it); the interruption timing is the modeled input. Do not let the harness
quietly re-introduce a tuned number — generate the barge-in behavior first, measure
second, report as-is (same rule as the corpus).

## Acceptance
- Runs on **native Windows**, no WSL2 (documented run command).
- G2 holds (a test: `chars_synthesized == generated`, not intended/`len(text)`).
- Produces the number: D7 $ + % of TTS spend + bootstrap CI + a barge-in-rate
  sweep table, from `record→price→detect→aggregate` on ≥100 harness calls.
- Honest provenance string as above. Suite green, ruff clean.

## Explicitly out of scope (Wave 3, not now)
Real-time conversation, real human barge-in timing, telephony, WSL2/Pipecat, ASR.
Those upgrade "modeled interruption timing" to "real" later; they are NOT needed
for a defensible measured headline this week.
