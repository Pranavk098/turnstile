# INGEST — the format your logs need (W3-A)

Point Turnstile at your calls: send each call as one JSON object in the shape
below, and `turnstile_ingest` maps it to a schema-valid v1.1 `Trace` and runs
the entire existing pipeline on it (price → adjudicate → detect → report).
No schema change, no re-instrumentation of the pipeline.

```bash
uv run python -m turnstile_ingest --sample                 # bundled 7-call sample
uv run python -m turnstile_ingest --in my-calls.json       # your file
uv run python -m turnstile_ingest --in my-calls.json --out ./out
```

Input is one call object, a `{"calls": [...]}` callset, or a bare list.
Output is `<out>/data.json` (fleet + findings + per-call reports + detector
coverage) plus a printed headline. `packages/ingest/data/data.json` is a
committed regeneration over the sample, so W3-B can build against it today.

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

## `data.json` shape (for W3-B)

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

## Sample

`packages/ingest/sample/calls.json`: seven hand-authored calls (billing
dispute ×2 incl. one escalation, refund, order status, cancellation-pending,
rescheduling, tech support). Generate-first / detect-second: written to read
like real logs, never tuned to detectors. No acoustic fields (the typical
real log), so D6/D7/D8 are absent throughout. Labeled `sample` in-file and
in every artifact; never present aggregates from it as fleet measurements.
