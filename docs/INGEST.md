# INGEST — the format your logs need

Point Turnstile at your calls: send each call as one JSON object in the shape
below, and `turnstile_ingest` maps it to a schema-valid v1.1 `Trace` and runs
the entire existing pipeline on it (price → adjudicate → detect → report).
No schema change, no re-instrumentation of the pipeline.

```bash
uv run python -m turnstile_ingest --sample                 # bundled 50-call sample
uv run python -m turnstile_ingest --in my-calls.json       # your file
uv run python -m turnstile_ingest --in my-calls.json --out ./out
```

Input is one call object, a `{"calls": [...]}` callset, or a bare list.
Output is `<out>/data.json` (fleet + findings + per-call reports + detector
coverage) plus a printed headline. `packages/ingest/data/data.json` is a
committed regeneration over the sample, so the dashboard can build against it today.

## The object

```json
{
  "id": "call-20260904-001",
  "scenario": "billing_dispute",
  "agent_version": "voice-agent@3.2.1",
  "started": "2026-09-04T09:02:11Z",
  "ended": "2026-09-04T09:02:41Z",
  "end_reason": "caller_hangup",
  "telephony": {"provider": "twilio", "direction": "inbound", "billable_seconds": 34},
  "turns": [
    {
      "start_ms": 0, "end_ms": 6800, "speaker_first": "caller", "barge_in": false,
      "asr": {"transcript": "Hi, I was charged twice.", "start_ms": 200, "duration_ms": 2500, "model": "nova-3"},
      "llm": {"model": "gpt-5-mini", "input_tokens": 820, "output_tokens": 14,
              "decision_kind": "route", "decision": "billing_dispute",
              "output_text": "I'll pull up your August bill and sort that out.",
              "start_ms": 2800, "duration_ms": 700},
      "tts": {"text": "I'll pull up your August bill and sort that out.", "start_ms": 3600, "duration_ms": 3000},
      "tools": [{"name": "lookup_invoices", "kind": "lookup", "effect": "none",
                 "args": {"customer_id": "C-10293"}}]
    }
  ]
}
```

Times are **call-relative wall milliseconds**: `turn.start_ms`/`end_ms` bound
the turn, span `start_ms` + `duration_ms` sit inside it. (This matches the
v1.1 `Trace` convention, verified against `fixtures/golden`.) Unknown fields
are rejected (`extra="forbid"`), so a typo fails loudly with the field path
instead of being silently dropped.

## Every field

Conversation:

| field | required | maps to | notes |
|---|---|---|---|
| `id` | yes | `conversation_id` | any unique string |
| `scenario` | yes | `scenario_id` | use a baselined id (`billing_dispute`, `refund`, `order_status`, `cancel_subscription`, `appointment_reschedule`, `tech_support`) or D4 stays silent for it (it guesses no threshold) |
| `started` / `ended` | yes | `started_at` / `ended_at` | ISO datetimes |
| `end_reason` | yes | `end_reason` | `caller_hangup` \| `agent_hangup` \| `escalated` \| `timeout` \| `error` |
| `agent_version` | no (`"unknown"`) | `agent_version` | pass yours through when the log has it |
| `telephony` | no | `TelephonyLeg` | one leg per call. `provider` (default `twilio`), `direction` (default `inbound`), `billable_seconds` (required when present). Absent → telephony cost 0 and **D8 ABSENT** (see below) |
| `turns` | yes, ≥1, wall order | `turns` | `turn_index` is positional |

Turn (`start_ms`/`end_ms` required; `speaker_first` default `caller`;
`barge_in` default `false`; at most one `asr`/`llm`/`tts` block each):

| block | required fields | defaults | maps to |
|---|---|---|---|
| `asr` | `transcript`, `start_ms`, `duration_ms` | `model nova-3`, `system deepgram`, `confidence 0.9`, `streaming true` | `AsrTranscribe` (`audio_seconds` = duration/1000) |
| `llm` | `model`, `input_tokens`, `output_tokens`, `decision_kind` (`route`\|`slot_fill`\|`tool_select`\|`compose`\|`escalate_check`), `decision`, **`output_text`**, `start_ms`, `duration_ms` | `system openai`, `decision_candidates [decision]`, `tool_calls []` (informational, unmapped), cache/reasoning tokens 0 | `LlmDecide` (`latency_ms` = duration) |
| `tts` | `text`, `start_ms`, `duration_ms` | `system piper`; **`chars_synthesized` / `chars_played` optional** | `TtsSynthesize` + `AudioPlayback`, **only when the char counts are present** |
| `tools[]` | `name`, **`kind`** (`retrieval`\|`mutation`\|`lookup`\|`handoff`), **`effect`** (`committed`\|`pending`\|`rejected`\|`none`\|`unknown`), `args` | `status ok`, `result null`, `start_ms` turn start, `duration_ms` 0, `cost_usd` 0.0 | `ToolCall` (`args_hash`/`result_hash` = sha256 of canonical JSON) |

Provider/model strings must resolve in `pricing/rates.yaml` (e.g. LLM
`openai/gpt-5-mini`, ASR `deepgram/nova-3`, TTS `piper`, telephony
`twilio/pstn_inbound`). A miss fails at load with the field path
(`turns[2].llm.model: LLM rate key 'acme/ultra' is not in ...`), not as a
`KeyError` inside pricing.

## What the adapter cannot map (honest omissions, not workarounds)

1. **TTS text/timing without G2 char counts.** `TtsSynthesize` requires
   `chars_synthesized` and G2 (`docs/GATES.md`) forbids `len(text)` as a
   stand-in, so a `tts` block without **both** `chars_synthesized` and
   `chars_played` yields **no tts/playback spans**. Consequences, all labeled
   in the report: TTS cost for the call is *unmeasured* (0 in `stage_costs`,
   which means "no data", not "free"), and detector classes **D6/D7/D8 are
   reported ABSENT** ("no data for this input") with their raw findings
   excluded. A block with only one of the two fields emits only that side's
   span. If the schema ever carries "text without measured chars" (e.g. an
   optional count or an unmeasured marker), that is a **schema-lane change**
   — flagged, not worked around here.
2. **`llm.tool_calls`.** Informational bookkeeping; v1.1 has no llm→tool
   link. The turn's `tools` list is authoritative.
3. **Per-turn telephony.** v1.1 carries one leg per trace; telephony is
   conversation-level in this format.

## Acoustic absence (Item 3): how "no data" differs from zero

| detector | no acoustic spans today | ingest report |
|---|---|---|
| D7 barge-in | `detect` returns `[]` — **identical** to measured-zero | ABSENT (the envelope is the only thing distinguishing them) |
| D8 silence-tax | with telephony it returns **inflated** gaps (speech time reads as silence) | ABSENT, raw findings excluded |
| D6 dead-tokens | **fires on every compose turn** (unvoiced output reads as dead) | ABSENT, raw findings excluded |
| D1–D5, D9, D10 | run on the log's real tokens/tools/verdict | PRESENT |

Coverage is call-level and conservative: any `tts` turn missing either char
count marks 6/7/8 absent for the whole call. D8 is additionally absent when
the telephony leg is missing.

## `data.json` shape (for the dashboard)

The CLI writes `<out>/data.json` plus one `call-<id>.json` per call, matching
the dashboard manifest's `INGEST_CONTRACT` (its `calls.json` rows and
per-call detail keys exactly; call ids match `[A-Za-z0-9_-]+`):

```
data.json:
{
  "label": ..., "n": 7, "note": ..., "provenance": "...",   # report envelope
  "sample": true,
  "fleet": {same keys as the dashboard's fleet.json: label, note,
            n_conversations, n_resolved, total_cost_usd, resolved_cost_usd,
            cprc_loaded, cprc_naive, recoverable_margin_pct,
            stage_costs_usd, _provenance},
  "coverage_summary": {"n_calls": 7, "calls_with_data_per_class": {"1": 7, ...}},
  "calls": [{"id", "scenario_id", "cost_usd", "verdict", "end_reason",
             "n_turns", "top_waste", "detail": "call-<id>.json"}],
  "findings": [...all reported findings, each with "call_id"...]
}
call-<id>.json:
{"trace", "span_costs", "turn_costs", "conv_cost", "stage_costs",
 "verdict", "findings", "top_waste_usd",
 "_provenance": {"ingest_call", "sample", "note", "coverage",
                "excluded_absent_classes"}}
```

`recoverable_margin_pct` uses the same §8.3 gate as the dashboard (D1
route→nano replay; 0.0 with no claim when the gate doesn't pass).
`excluded_absent_classes` names classes whose raw findings were dropped for
lack of data — auditability for the honesty claim.

Margin-denominator choice (headline semantics, stated plainly): the % is
computed over the **measurable subset only** — provider-adapted calls whose
`decision_kind` was inferred are excluded from *both* the proven-savings
numerator and the spend denominator, and the exclusion is disclosed in the
fleet note (`coverage_summary.margin_excluded` carries the count). This keeps
the % a true statement about the analyzable spend: including unmeasurable
calls in the denominator would dilute it, and letting inferred labels into the
numerator would inflate it. See [LIMITATIONS.md](LIMITATIONS.md) for what
"measurable" excludes.

## Sample

`packages/ingest/sample/calls.json`: seven hand-authored calls (billing
dispute ×2 incl. one escalation, refund, order status, cancellation-pending,
rescheduling, tech support). Generate-first / detect-second: written to read
like real logs, never tuned to detectors. No acoustic fields (the typical
real log), so D6/D7/D8 are absent throughout. Labeled `sample` in-file and
in every artifact; never present aggregates from it as fleet measurements.

## Vapi provider exports

A real Vapi call export runs end-to-end with no re-instrumentation: the
adapter (`packages/ingest/src/turnstile_ingest/providers/vapi.py`) maps one
Vapi call object to the `IngestCall` format above, then the **existing**
pipeline runs unchanged (price → adjudicate → detect → report).

```bash
uv run python -m turnstile_ingest --provider vapi --in vapi-export.json --out ./out
# --provider {turnstile,vapi}; default "turnstile" (the native format above).
# With no --in, --provider vapi runs the bundled Vapi sample.
```

Input is one Vapi call object, a bare list, or a list-wrapper (`{"calls"}`,
`{"results"}` (Vapi's list shape), or `{"data"}`). Output is the standard
`<out>/data.json` + per-call files; the report envelope carries
`source: Vapi export ...` in its provenance, and each per-call
`_provenance` records the provider, the export version, and which fields
were inferred vs. read directly.

### Mapping table

Vapi field names verified Sep 2026 against the published Call schema
(`docs.vapi.ai/api-reference/calls/*`), the ended-reason catalog
(`docs.vapi.ai/calls/call-ended-reason`), and the `CostBreakdown` /
`UserMessage` / `BotMessage` / `ToolCallMessage` / `ToolCallResultMessage`
schemas:

| `IngestCall` | Vapi source | Notes |
|---|---|---|
| `id` | `id` | UUIDs pass the dashboard's `[A-Za-z0-9_-]+` route |
| `scenario` | `assistant.name` → `name` → `squad.name`/`squadId` | slugified (`Billing Assistant` → `billing_assistant`); absent → `"unknown"` (D4 then stays silent, as for any unbaselined id) |
| `agent_version` | `assistantId` | as `vapi/<id>`; absent → `vapi/unknown` |
| `started` / `ended` | `startedAt` / `endedAt` | RFC3339; both required |
| `end_reason` | `endedReason` | exact table for the common codes (`customer-ended-call` → `caller_hangup`, `assistant-ended-call*` → `agent_hangup`, `assistant-forwarded-call` → `escalated`, `exceeded-max-duration` / `silence-timed-out` → `timeout`), error families by prefix (`pipeline-error-*`, `call.start.*`, `call.in-progress.*`, …) plus the no-answer/connectivity codes → `error`. Anything else → `IngestError` naming the value |
| `telephony` | `type` + `phoneCallProvider` + call duration | `inboundPhoneCall` → `inbound`, `outboundPhoneCall` → `outbound`; `webCall` / `vapi.websocketCall` carry no phone leg → omitted (D8 ABSENT). `billable_seconds` from `endedAt − startedAt`. The provider string passes through exactly — it must resolve in `pricing/rates.yaml` (see below) |
| `turns[]` | `artifact.messages` (else top-level `messages`) | time-ordered by `secondsFromStart` (clamped ≥ 0); each `user` message opens a turn, agent/tool messages attach to the open turn, pre-first-user messages form an opening agent-first turn. Unknown roles raise |
| `turn.asr` | `user` message text + `time`/`endTime` timing | transcriber from `assistant.transcriber` when present, else `deepgram/nova-3` defaults |
| `turn.llm` model/tokens | `assistant.model.{provider,model}` + `costBreakdown.{llmPromptTokens,llmCompletionTokens,llmCachedPromptTokens}` | call-level totals only — see "honest approximations" below |
| `turn.llm.decision_kind` | **not emitted by Vapi — inferred + flagged** | rule below; D1 never fires on it (§5 boundary) |
| `turn.llm.output_text` | `bot`/`assistant` message text | required; never copied from `tts.text` |
| `turn.tts` | `bot`/`assistant` message text + timing | **text only, no char counts** → no tts/playback spans → D6/D7/D8 ABSENT |
| `turn.tools[]` | `tool_calls` + `tool_call_result` messages joined by tool id | `kind` from documented name rules (override with `tool_kinds={name: kind}`); `effect` from the result (`error` → `rejected`; pending markers → `pending`; bare `result` → `committed` for mutation/handoff; reads always `none`; missing/ambiguous → `unknown`). Contradictory (both `result` and `error`) → `IngestError` |

### Honest approximations (flagged in provenance, never silent)

1. **`decision_kind` inference.** Rule: a turn triggering a mutation/handoff
   tool → `tool_select`; the call's first LLM turn → `route`; otherwise
   `compose`. `slot_fill` / `escalate_check` are never inferred. Every
   adapted turn is flagged (`inferred_decision_turns` in per-call
   `_provenance`), D1 is ABSENT for fully-inferred calls, residual D1
   findings on inferred turns are dropped, and fully-inferred calls are
   excluded from the recoverable-margin replay. An inferred label never
   feeds a headline number.
2. **Token distribution.** `costBreakdown` carries call-level totals only, so
   they are split evenly across the call's LLM turns with the exact sum
   preserved (per-turn attribution is approximate; even — not
   text-proportional — so no fake token slope for D2 to misread).
3. **TTS omission.** `costBreakdown.ttsCharacters` is call-level, never
   per-message, so per-turn char counts would be invented either way: the
   adapter omits them and D6/D7/D8 read ABSENT. Vapi's own cost split is
   still visible in the export; Turnstile prices only what it measures.

### What your export needs

- `assistant.model.{provider,model}` must resolve in `pricing/rates.yaml`
  (same rule as native logs: `openai/gpt-5-mini` works out of the box; a
  `gpt-4o` assistant needs its rate row added — the error names the key).
  Provider prefixes are stripped (`openai/gpt-4o` → `gpt-5`-style bare
  `gpt-4o` under its own provider).
- `phoneCallProvider` passes through: `twilio` works out of the box;
  `vonage`/`telnyx`/`vapi` legs, or `outbound` direction, need their
  `provider/pstn_<direction>` rate row (the error lists known keys).
- Tools with names outside the documented rules need ground truth:
  `from_vapi(call, tool_kinds={"my_tool": "mutation"})`.

### Vapi sample

`packages/ingest/sample/vapi-export.sample.json`: one hand-authored,
schema-conformant **synthetic** billing-dispute export (NOT real customer
traffic — labeled `sample` in-file, in the CLI headline, and in every
artifact's provenance). Greeting + complaint + invoice lookup + authorized
correction + close; resolves `RESOLVED` with D1/D6/D7/D8 honestly ABSENT.

## Retell provider exports

A real Retell Get Call export runs end-to-end with no re-instrumentation: the
adapter (`packages/ingest/src/turnstile_ingest/providers/retell.py`) maps one
Retell call object to the `IngestCall` format above, then the **existing**
pipeline runs unchanged (price → adjudicate → detect → report).

```bash
uv run python -m turnstile_ingest --provider retell --in retell-export.json --llm-identity openai/gpt-5-mini --out ./out
# --provider {turnstile,vapi,retell}; default "turnstile" (the native format above).
# With no --in, --provider retell runs the bundled Retell sample.
# --llm-identity SYSTEM/MODEL is required for real exports (Retell names no
# model); the bundled sample carries embedded ground truth and runs without it.
```

Input is one Retell call object, a bare list, or a list-wrapper (`{"calls"}`,
`{"results"}`, or `{"data"}`). Output is the standard `<out>/data.json` +
per-call files; the report envelope carries `source: Retell export ...` in
its provenance, and each per-call `_provenance` records the provider, the
export/spec revision, and which fields were inferred vs. read directly.

### Mapping table

Retell field names verified Sep 2026 against the published Get Call schema
(`https://docs.retellai.com/api-references/get-call`, OpenAPI
`x-retell-spec-revision: 2026-09-14-b240eb0`), the disconnection-reason
catalog (`https://docs.retellai.com/reliability/debug-call-disconnect`), and
the latency/token notes
(`https://docs.retellai.com/reliability/check-actual-latency`):

| `IngestCall` | Retell source | Notes |
|---|---|---|
| `id` | `call_id` | alphanumeric ids pass the dashboard's `[A-Za-z0-9_-]+` route |
| `scenario` | `agent_name` | slugified (`Billing Assistant` → `billing_assistant`); absent → `"unknown"` (D4 then stays silent, as for any unbaselined id) |
| `agent_version` | `agent_id` + `agent_version` (**int**) | as `retell/<agent_id>.v<version>` (e.g. `retell/agent-abc.v3`); missing/empty `agent_id` or non-int version → `IngestError` |
| `started` / `ended` | `start_timestamp` / `end_timestamp` | **epoch ms ints**; both required |
| `end_reason` | `disconnection_reason` | explicit table: `user_hangup` → `caller_hangup`; `agent_hangup` → `agent_hangup`; `call_transfer` / `transfer_bridged` → `escalated`; `inactivity` / `max_duration_reached` → `timeout`; every other documented code (voicemail/IVR landings, dial/SIP failures, payment/concurrency blocks, all `error_*`, `registered_call_timeout`, `transfer_cancelled`, `manual_stopped`, `call_take_over`, …) → `error`. Anything else → `IngestError` naming the value. `call_status != "ended"` → `IngestError` (only ended calls are ingestible) |
| `telephony` | `call_type` + `direction` + `duration_ms` | `phone_call` → leg with the caller-supplied provider (see below), `direction` straight through, `billable_seconds` = round(`duration_ms`/1000). `web_call` carries no phone leg → omitted (D8 ABSENT). Unknown `call_type`, missing/invalid `direction`, or missing `duration_ms` on a phone call → `IngestError`. `from_number` / `to_number` / `transfer_destination` are addressing/bookkeeping, not mapped |
| `turns[]` | `transcript_with_tool_calls` (else `transcript_object`) | preferred timeline wins when non-empty; each `user` / `transfer_target` utterance opens a turn, agent/tool entries attach to the open turn, pre-first-user entries form an opening agent-first turn. `transfer_target` speech rides caller-side as ASR (it is not the agent's — never an LLM decision). Unknown entry roles raise |
| `turn.asr` | `user` / `transfer_target` utterance content + word timing | transcriber always the ingest default `deepgram/nova-3` (Retell names none) |
| `turn.llm` model/tokens | **caller-supplied `llm_identity=(system, model)`** (else the export's embedded `agent_model` fixture key) + `llm_token_usage.values[]` | Retell names no model — see "honest approximations" below |
| `turn.llm.decision_kind` | **not emitted by Retell — inferred + flagged** | same rule as Vapi (mutation/handoff-triggering turn → `tool_select`; first LLM turn → `route`; else `compose`; never `slot_fill`/`escalate_check`); D1 never fires on it (honesty boundary) |
| `turn.llm.output_text` | `agent` utterance content | required; never copied from `tts.text` |
| `turn.tts` | `agent` utterance content + word timing | **text only, no char counts** (Retell emits none) → no tts/playback spans → D6/D7/D8 ABSENT |
| `turn.tools[]` | `tool_call_invocation` + `tool_call_result` entries joined by `tool_call_id` | `kind` from documented name rules (override with `tool_kinds={name: kind}`); `effect` from `successful`/`content` (`successful: false` or explicit `error` payload → `rejected`; pending markers → `pending`; bare success result → `committed` for mutation/handoff; reads always `none`; missing/ambiguous → `unknown`). Content carrying both `result` and `error` → `IngestError`. `dtmf` / `sms` / `injected` entries are not spoken turns (skipped); `node_transition` is flow bookkeeping (informational, never a turn) |
| — | `call_cost`, `latency`, `call_analysis`, `recording_url`, `public_log_url`, `transcript` | never mapped: billing summary / latency stats / post-call analysis / media URLs / flat text are not pricing inputs (using them as token sources would fabricate telemetry) |

### Honest approximations (flagged in provenance, never silent)

1. **`llm_identity` (no invented model).** The Get Call schema carries no
   model field, so the adapter takes the backing model as caller-supplied
   ground truth: `from_retell(call, llm_identity=("openai", "gpt-5-mini"))`
   (any `pricing/rates.yaml`-resolvable model), falling back to a top-level
   `agent_model: {"system", "model"}` key hand-authored into the export
   itself (synthetic fixtures only). A call with agent turns and neither
   raises `IngestError` naming `llm_identity` — the exact analog
   of the Vapi adapter's `assistant.model` requirement. The provenance note
   records the priced identity and its channel.
2. **Token distribution without a prompt/completion split.**
   `llm_token_usage` carries combined per-request counts only, so the call
   total (sum of `values`) is split evenly across the call's LLM turns as
   `input_tokens` with `output_tokens` 0 — exact sum preserved in `input`,
   per-turn attribution approximate (even, not text-proportional, so no fake
   token slope for D2 to misread). Output cost is thereby *unmeasured*, not
   zero; LLM cost reads as a lower bound and the provenance note says so.
   Absent `llm_token_usage` (custom LLM / realtime API / no LLM call) with
   agent turns present → `IngestError`, never invented tokens.
3. **`decision_kind` inference.** Same rule as Vapi: a turn triggering a
   mutation/handoff tool → `tool_select`; the call's first LLM turn →
   `route`; otherwise `compose`. `slot_fill` / `escalate_check` are never
   inferred. Every adapted LLM turn is flagged (`inferred_decision_turns`
   in per-call `_provenance`), D1 is ABSENT for fully-inferred calls,
   residual D1 findings on inferred turns are dropped, and fully-inferred
   calls are excluded from the recoverable-margin replay. An inferred label
   never feeds a headline number.
4. **Word-timing approximation.** Word `start`/`end` are relative audio
   seconds Retell documents as "not guaranteed to be accurate"; the utterance
   window runs first-word-start → last-word-end. An utterance without usable
   word timings is placed by evenly dividing the call duration in document
   order, and the provenance note names the count.
5. **Telephony default.** Retell names no PSTN provider, so `phone_call`
   legs bill through the explicit `telephony_provider` parameter (default
   `"twilio"`). The default is an assumption, stated in the module docstring,
   the provenance note, and here: the `<provider>/pstn_<direction>` rate key
   must exist in `pricing/rates.yaml` (a miss fails at load naming the key —
   `twilio/pstn_inbound` works out of the box; anything else needs its row
   verified and added, same as the Vapi-leg template).
6. **TTS omission.** No per-turn char counts exist to read, so per-turn char
   counts would be invented either way: the adapter omits them and D6/D7/D8
   read ABSENT. Retell's own `call_cost` split is still visible in the
   export; Turnstile prices only what it measures.

### What your export needs

- `call_status: "ended"` — only ended calls are ingestible (anything else
  raises naming `call_status`).
- `transcript_with_tool_calls` or `transcript_object` non-empty — else
  raises naming both paths. Prefer exports with word timings; without them
  placement is approximate (flagged, never silent).
- `llm_identity` for the backing model (see #1 above) resolving in
  `pricing/rates.yaml` (e.g. `("openai", "gpt-5-mini")` works out of the
  box): pass `--llm-identity openai/gpt-5-mini` on the CLI, which wins; else
  a top-level `agent_model: {"system": ..., "model": ...}` key in the export
  itself counts as hand-authored ground truth (how the bundled sample runs
  flag-free). A real export with neither fails loudly naming `llm_identity`
  (no silent default exists to fall back to).
- `llm_token_usage.values` non-empty when the call has agent turns (absent
  with custom LLM / realtime API → the adapter raises rather than invent
  tokens).
- Phone calls bill through `telephony_provider` (default `"twilio"`): a
  non-Twilio leg needs its `<provider>/pstn_<direction>` rate row (the load
  error names the key).
- Tools with names outside the documented rules need ground truth:
  `from_retell(call, tool_kinds={"my_tool": "mutation"})`.

### Retell sample

`packages/ingest/sample/retell-export.sample.json` (Track B): one
hand-authored, schema-conformant **synthetic** billing-dispute export (NOT
real customer traffic — labeled `sample` in-file, in the CLI headline, and
in every artifact's provenance). Greeting + complaint + invoice lookup +
authorized correction + close over `transcript_with_tool_calls` (flat
role-discriminated entries) with a matching word-timed `transcript_object`;
`llm_token_usage` totals 4050 combined tokens; resolves `RESOLVED` with
D1/D6/D7/D8 honestly ABSENT. It carries embedded `agent_model:
{"system": "openai", "model": "gpt-5-mini"}` ground truth (a real export
never has this key — the schema has no such field), so it prices without
`--llm-identity`; a real export needs the flag.
