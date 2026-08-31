# GLM 5.3 task brief — G1: TraceRecorder concurrency redesign

Hand this to GLM 5.3 in its `opencode/*` worktree (branched off the current `wave0-foundation`). TDD, every step green + committed. This is a **breaking API change**, self-contained in `packages/otel/`.

---

**MISSION:** Redesign `TraceRecorder` so a turn's spans can **overlap in time** (TTS streaming during LLM decode; next-turn compute starting during the prior turn's playback), so that live-recorded traces express real concurrency. Today the recorder can only emit contiguous, non-overlapping spans — which means Detector 8 (silence tax) systematically over-reports on live traffic, and the recorder cannot reproduce the two golden overlap fixtures. Fixing this is the prerequisite for **trusting** D8's numbers and for the live `agent/` build (`docs/GATES.md` G1).

**READ FIRST:** `docs/GATES.md` (G1 + G2), `docs/DEMO.md` (why the tier split hinges on this), the current `packages/otel/src/turnstile_otel/recorder.py`, and the two overlap fixtures `fixtures/golden/08_silence_tax.json` and `19_edge_40_turn.json` (these encode the overlap shapes the recorder must be able to produce).

**PACKAGE:** `packages/otel/` ONLY. You may read `packages/schema/` but MUST NOT modify it or `fixtures/golden/` (owner-authored per PRD §10.2).

**THE PROBLEM (be precise):**
- `_advance()` forces each stage's `start` to the previous stage's `cursor` → spans are always contiguous, never overlapping.
- Turns are consumed via sequential `with rec.start_turn(N) as turn:` blocks; turn N+1's `__enter__` (which reads the clock) cannot run until turn N's `__exit__` returns → cross-turn overlap (fixture 19) is impossible under any calling pattern.

**THE REDESIGN:**
- Represent turns as **objects with independent start/end lifetimes**, not strictly-nested `with` blocks. A turn can be opened, have spans recorded against an explicit or derived absolute timeline, and be finalized — and a later turn's spans may carry `start_offset_ms` that overlaps an earlier turn's spans.
- Each `record_*` must be able to specify (or derive) a `start_offset_ms` that MAY overlap a previously-recorded span (e.g. a TTS span starting mid-LLM). Provide an ergonomic way to say "this span starts at absolute offset X" or "this span starts D ms into the previous span," so overlap is expressible, not forced-contiguous.
- Keep everything else: real OTel span emission with `gen_ai.*` + `turnstile.*` attributes (INCLUDING `turnstile.start_offset_ms`/`turnstile.duration_ms` — the audit's CR-04 area), the schema-v1.1 `ToolCall` validator pass-through, and **G2**: `chars_synthesized` stays a REQUIRED parameter (no `len(text)` fallback).
- Preserve deterministic-clock injection for tests.

**ACCEPTANCE (the real gate):**
- A contract test builds a trace via the NEW recorder that **reproduces the overlap shape of fixture 08** (a TTS span overlapping/adjacent to the compute spans with the trailing silence gap intact) AND **fixture 19** (a next-turn `llm.decide` overlapping the prior turn's `audio.playback` — "shape B"). Assert the produced `Trace` is schema-valid AND that `turnstile_detectors.detect_silence_tax`'s union computation sees the overlap (union < sum) on the overlapping trace — i.e. the recorder can now emit what D8 was built to measure.
- Existing otel tests updated to the new API (it's a breaking change; there is no live agent yet, so the only callers are tests).
- `InMemorySpanExporter` test still confirms real OTel spans carry the `gen_ai.*` + `turnstile.*` attrs including offset/duration.
- `uv run pytest packages/otel -q` green; full workspace `uv run pytest -q` green.

**BOUNDARIES:** `packages/otel/` only. No schema/fixtures edits. No contract-signature changes outside otel. No OpenAI/credit. Work in an `opencode/*` branch off the current `wave0-foundation`; TDD; end green + committed.

**REPORT:** the new turn/span lifetime model; how overlap is expressed; the two reproduced overlap shapes + the union-sees-overlap assertion; the API migration (old→new) for otel's own tests; confirmation G2 + offset/duration emission preserved; concerns.
