# Hard gates before / around the live `agent/` build

Owner-flagged structural gates that must be honored before their dependent work
is *trusted*, not just before it runs. These are stronger than "nice-to-have"
follow-ups.

## G1 — Recorder concurrency redesign (blocks trusting D8, not just `agent/`)

**Problem.** The `otel` `TraceRecorder` uses a per-turn monotonic cursor and
nested `with`-block turns, so it can only emit **contiguous, non-overlapping**
spans. It architecturally cannot produce TTS-during-LLM or cross-turn overlap.
Golden fixtures `08_silence_tax` and `19_edge_40_turn` encode exactly that
overlap — so **the hand-authored fixtures and the live instrumentation
disagree about what a valid trace looks like, and only the fixtures are
correct.**

**Consequence (the second-order one).** Detector 8 (silence tax) is built and
validated against the fixtures' overlap. But the live recorder will never emit
overlap, so `union == sum` on every real trace: D8 will pass contract-test on
fixtures and then **systematically over-report silence/waste on real traffic.**

**Ruling.** The concurrency redesign — turns as objects with independent
start/end lifetimes rather than nested `with` blocks, spans allowed to overlap —
is a **prerequisite for trusting D8's numbers**, and a breaking change to the
`TraceRecorder` public API. Until it lands:
- D8's fixture results are **a demo of the detector, not a measurement**. Say so in `LIMITATIONS.md`.
- Do it **before** `agent/` integration (the API the agent builds against must be the post-redesign one).

## G2 — TTS must report `generated` (billed), not `intended` (blocks trusting D7)

**Problem.** On barge-in, unheard characters split two ways:
- **synthesized then discarded unheard** → billed → real D7 waste.
- **never synthesized** (generation cancelled) → never billed → counting them **inflates** D7.

A pipeline that only knows "played 61 of 184" cannot tell these apart, and
overstates D7 in exactly the direction a skeptic attacks.

**Ruling.** The live agent's TTS wrapper MUST set
`tts.synthesize.chars_synthesized = characters actually generated before
cancellation` (BILLED) — never the intended text length. Detector 7 computes
`chars_synthesized − chars_played`, so this is load-bearing for D7's honesty.
The kill-check probe (`packages/agent/spikes/playback_probe.py`) validates that
the pipeline can report `generated` distinctly from `played` and `intended`.

---

Both gates trace to the same root: **the instrument must not claim precision the
underlying pipeline doesn't actually have.** That discipline is the product.
