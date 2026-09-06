# Wave-2 Item 1 viability note (free half done; gated probe pending)

## Labels per kind (measured free, corpus n=250/seed 8)

| kind | decisions | labels |
|---|---|---|
| `escalate_check` | 185 | continue / escalate (terminal-handoff spans carry `["resolve", "escalate"]`) |
| `tool_select` | 425 | retrieve_kb_article / lookup_account |
| `slot_fill` | 443 | request_slot (single label) |
| `route` | 217 | 6 scenarios + `other` per-span (`[scenario_id, "other"]`) |
| `compose` | 600 | inform / complete_mutation / close_call (singletons per span) |

Bounded, meaningful vocabulary — Item 1 step 1 passes.

## Prompt contract (implemented, `OpenAIBackend._render_messages`)

Bounded kinds (`route`, `compose`, `tool_select`, `escalate_check`) get:
`Reply naturally, but include exactly one of these decision labels verbatim
in your reply: {span's own candidates}.`
`slot_fill` is excluded (single-label, verdict-content-sensitive).

## Parser behavior on authored utterances (unit-tested, free)

- Elicited-style replies (`"...billing_dispute..."`) parse to the label;
  longest-contained-candidate wins (`order_status` over `other`).
- Natural prose without the verbatim label abstains (raw passthrough, never
  fabricated) — including the underscore gap (`"close this call"` has no
  `"close_call"`). Elicitation is load-bearing.
- `["resolve", "escalate"]` + bare `"resolve"` → `continue` (pinned; resolve ~=
  handle-without-escalation).

## Pending: real-model parse reliability (owner-gated ≤5-call probe)

Design: one elicited replay per kind (`route`, `compose`, `tool_select`,
`escalate_check`, `slot_fill` as no-elicitation control) through
`OpenAIBackend` on real corpus spans; report fraction parsing to an in-vocab
label. Suggested bar: ≥4/5 (slot_fill control expected to abstain) → go Item 2;
else stop and report. Estimated spend: fractions of a cent.

**No paid call has been made for this note. Awaiting owner go for the probe.**
