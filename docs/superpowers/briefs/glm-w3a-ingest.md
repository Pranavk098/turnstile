# GLM brief — W3-A: `turnstile_ingest`, the real-data front door

**Base:** `wave0-foundation` @ current tip. Branch `opencode/w3a-ingest` (may be a
stacked series). Claude reviews + merges. Independent of W3-B — start immediately.

## Goal
Give Turnstile a documented **input format** ("give me your calls in THIS shape") and
an adapter that maps it → the frozen v1.1 `Trace`, so the *entire existing pipeline*
(price → adjudicate → detect → report) runs on **real, non-synthetic** call data. Plus
a small realistic sample so the product runs today. This is the FDE motion: *"point it
at your calls, here's your number."*

## Boundaries & discipline (hard)
- **New package `packages/ingest/` (`turnstile_ingest`).** It READS the frozen schema
  and maps TO it — **never edit `packages/schema/` or `fixtures/golden/`.** If a real
  field can't map to v1.1 without a schema change → **STOP and flag** (schema is
  owner-lane/frozen).
- **Do NOT do the Task-2 B/C package merges here** (stats→replay, otel→agent). Add
  `ingest` as a normal new package; the layout migration is a separate batch.
- Honesty carries over: the sample is labeled a **sample**, authored generate-first /
  detect-second (**never tuned to make detectors fire**, same as the corpus contract).
- Each branch ends green + `ruff check packages/` clean.

## Item 1 — the ingest format (`docs/INGEST.md` + a Pydantic model)
Define a clean external JSON format for one call — essentially what a real voice-AI
platform log carries, simpler than the internal `Trace`: a conversation
(id/scenario/started/ended/end_reason) and turns, each with optional
`asr` (transcript, start_ms, duration_ms, model), `llm` (model, input_tokens,
output_tokens, decision_kind, decision, tool_calls, start_ms, duration_ms),
`tts` (text, start_ms, duration_ms, and OPTIONAL acoustic fields
`chars_synthesized`/`chars_played`), `tools` (name, args, effect, status), and
`telephony` (provider, direction, billable_seconds). Document every field + a full
example in `docs/INGEST.md` — this doubles as the "here's the format your logs need"
one-pager. Model it with Pydantic (validates on load).

## Item 2 — the adapter `turnstile_ingest.load(obj) -> Trace`
Map the ingest format → a schema-valid v1.1 `Trace` (fill span offsets, ids, required
fields). Clear errors pointing at the bad field when input is malformed. Then the
existing `price_trace` / `adjudicate` / `detect` run unchanged.

## Item 3 — HONEST acoustic-absence handling (critical)
A real platform log usually will NOT carry the G2 acoustic fields (`chars_synthesized`
= generated-before-cancellation, `chars_played`). When those are absent, the acoustic
detectors **D7 (barge-in) and D8 (silence-tax) must be reported ABSENT / "no data for
this input" — never zero, never faked.** The cost/verdict/LLM detectors (D1–D5, D9,
D10) still run on the real telemetry. This is the whole honesty thesis on real data:
say what you can't measure.

## Item 4 — a small realistic sample (5–10 calls, in the ingest format)
Author a handful of realistic, varied calls (billing dispute, refund, order status,
etc.) with **natural caller utterances** and realistic timings/tokens/tool outcomes —
generate first, do not peek at detector output to tune them. Label it a sample in the
file + docs. Bundle it so the product demos on believable data today.

## Item 5 — CLI / entry
`turnstile_ingest` CLI (or `run_ingest.py`): read an ingest JSON (file or the sample) →
full pipeline → the same report/`data.json` shape the dashboard consumes (so W3-B can
render real data). Print the headline (recoverable margin + which detectors had data).

## Acceptance
- `docs/INGEST.md` (documented format + example); Pydantic model validates.
- Round-trip test: sample → `load()` → valid `Trace` → prices/adjudicates/detects with
  no error. Malformed-input test: clear field-pointed error.
- Acoustic-absence test: a call with no acoustic fields runs the full pipeline and
  D7/D8 are labeled absent (asserted), not zero.
- Whole sample ingests + produces a report; a data artifact the dashboard can read.
- Suite green, ruff clean. **STOP-and-flag** on any schema-change need.
