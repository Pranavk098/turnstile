# PRD 02 — Real voice-provider log adapter (+ sample)

**Owner (spec):** Pranav Koduru · **Executor:** OpenCode · **Reviewer:** Claude
**Status:** ready to build · **Roadmap item:** #2 (one real-shaped data run)

---

## 1. Thesis

Every Turnstile headline today is "the number on *this* synthetic data." The single
highest-value credibility step is making **"run it on your own calls" literally
true**: a user exports a call from a real voice-agent platform and Turnstile prices,
adjudicates, and audits it with **no re-instrumentation**.

The existing `turnstile_ingest` already accepts an *external* format
(`IngestCall`, `docs/INGEST.md`) and runs the whole pipeline on it. This feature
adds **one adapter that maps a real provider's call-export format into that
`IngestCall` format**, plus one clearly-labeled sample export, and surfaces the
result on the dashboard with correct provenance. Chosen provider: **Vapi** — its
call object is publicly documented and already carries a per-provider cost
breakdown, transcript, message timeline, and end reason, which map cleanly onto
Turnstile's spans. (Retell/LiveKit are documented as future adapters, §10.)

## 2. Non-goals

- **No paid calls.** The adapter is pure data transformation; the sample is a
  committed file. Nothing in this feature calls a provider API or a model. See §3.
- **No fabricated "real fleet" claim.** If the sample export is hand-authored to the
  provider's schema rather than pulled from a real account, it is labeled a
  **schema-conformant synthetic example**, not real customer traffic. The *adapter*
  is what makes real data work; the sample only demonstrates the mapping.
- **No schema change.** The adapter targets the existing `IngestCall` external
  format; the frozen v1.1 `Trace` and PRD §3–5 are untouched.
- **No inference of numbers Turnstile cannot honestly derive** (see §5 — the
  `decision_kind` boundary is the crux and must be handled honestly, not papered
  over).

## 3. Hard constraints

1. **$0.** No provider-API calls, no model calls, no paid anything, in code or in
   the acceptance path.
2. **Honesty labeling is load-bearing.** Fields the provider does not emit are
   **not invented**. Absent acoustic char counts → the adapter emits no tts/playback
   spans and the pipeline reports D6/D7/D8 **ABSENT** (this behavior already exists
   in `IngestTts.acoustic_complete` and the pipeline's coverage envelope — reuse
   it, do not bypass it).
3. **Loud failure over silent guessing.** `IngestCall` is `extra="forbid"`; keep it.
   A provider field that cannot be mapped either maps explicitly or raises
   `IngestError` with the source field path — never a silent drop or a `len(text)`
   stand-in.
4. **Provenance recorded per call.** Every adapted call records, in a provenance
   note that rides through to the dashboard: source provider + export version, and
   **which fields were inferred vs. read directly** (esp. `decision_kind`, §5).

## 4. Interface

New module: `packages/ingest/src/turnstile_ingest/providers/vapi.py`

```python
def from_vapi(call_obj: dict) -> IngestCall: ...
# maps ONE Vapi call export object -> the external IngestCall format.
def from_vapi_export(obj: dict | list) -> list[IngestCall]: ...
# a single call, a list, or Vapi's list-wrapper -> IngestCall list.
```

CLI extension (`turnstile_ingest.__main__`):

```bash
uv run python -m turnstile_ingest --provider vapi --in vapi-export.json --out ./out
# --provider {turnstile,vapi}; default "turnstile" (today's native external format)
```

`--provider vapi` runs `from_vapi_export` first, then the **existing**
`run_calls` pipeline unchanged. No new pipeline, no new report shape.

### 4.1 Mapping table (author against Vapi's public call schema; verify field names)

| Turnstile `IngestCall` | Vapi source | Notes |
|---|---|---|
| `id` | call `id` | |
| `scenario` | assistant name / squad / metadata tag | if absent → `"unknown"` |
| `started` / `ended` | `startedAt` / `endedAt` | RFC3339 |
| `end_reason` | `endedReason` | map to `EndReason` enum; unmapped value → `IngestError` |
| `telephony.billable_seconds` | call duration / `costBreakdown.transport` basis | conversation-level leg only |
| `turns[]` | `messages[]` / transcript timeline | group into caller/agent turns by role + timestamps |
| `turn.asr.transcript` | user message text | `start_ms`/`duration_ms` from message timing |
| `turn.llm.*` tokens | `costBreakdown` / model usage if present | if per-turn tokens absent → see §5 |
| `turn.llm.decision_kind` | **not emitted by Vapi** | **§5 — inferred + flagged, never fed to D1 as real** |
| `turn.llm.output_text` | assistant message text | required; never copied from tts.text |
| `turn.tts.text` | assistant spoken text | `chars_synthesized`/`chars_played` **absent → omit spans** |
| `turn.tools[]` | tool/function-call messages | `kind`/`effect` required — map from tool result status; unresolved → `effect=unknown` |

(The exact Vapi field names must be taken from Vapi's current published call/webhook
docs at build time and cited in `docs/INGEST.md`; treat the column above as the
mapping contract, not as verified field spellings.)

## 5. The `decision_kind` honesty boundary (the crux — read carefully)

`turnstile-prd.md` §3.2 states `decision_kind` **must be emitted by the agent, not
inferred**, and D1 (over-model) is "unbuildable without it." Real provider logs
(Vapi included) **do not emit `decision_kind`.** The adapter must therefore:

- Infer `decision_kind` **only** where deterministically safe and document the rule:
  e.g. turn 0 with route-like candidates → `route`; a turn whose agent message
  triggers a mutation/handoff tool → `tool_select`; otherwise `compose`.
- **Flag every inferred `decision_kind` in provenance** (`decision_kind_source:
  "inferred" | "provider"`).
- Ensure **D1 does not fire on inferred `decision_kind`** — either suppress D1 for
  inferred-kind spans or have the pipeline mark those D1 findings as
  `provenance: inferred_decision_kind` so they are never reported as measured
  over-model waste. Confirm the exact suppression path with the reviewer; the
  invariant is: **no inferred label may masquerade as an agent-emitted one in a
  headline number.**

This boundary *is* the feature's credibility. Getting it right matters more than
maximizing how many detectors light up.

## 6. Build phases

- **P0 — Enum + reason mapping.** `endedReason` → `EndReason`, tool status → `Effect`,
  with an explicit unmapped-value error. *Verify:* unit tests incl. an unmapped
  reason raising `IngestError` with the source value.
- **P1 — `from_vapi` core.** One Vapi call object → valid `IngestCall`; turn grouping;
  acoustic-absence handled by omission. *Verify:* a fixture Vapi object maps to an
  `IngestCall` that `adapter.load` accepts and prices; absent acoustics → D6/D7/D8
  ABSENT in coverage.
- **P2 — `decision_kind` inference + provenance flags** (§5). *Verify:* inferred
  kinds are flagged; a test asserts D1 never reports inferred-kind spans as measured
  waste.
- **P3 — CLI `--provider vapi` + sample.** Wire the flag; commit one
  `packages/ingest/sample/vapi-export.sample.json` labeled synthetic-schema-conformant;
  regenerate `data.json`. *Verify:* `uv run python -m turnstile_ingest --provider vapi
  --in <sample>` prints a headline and writes `data.json`; provenance names the source.
- **P4 — Docs + dashboard surfacing.** Add the Vapi mapping table + a real example to
  `docs/INGEST.md`; the dashboard fleet view labels the source and its tier. *Verify:*
  dashboard renders the adapted sample with a visible "source: Vapi export (synthetic
  example)" provenance line and correct ABSENT detectors.

## 7. Definition of Done (prod-ready / feature-ready)

- [ ] `from_vapi` / `from_vapi_export` map the documented Vapi call schema to valid
      `IngestCall`(s); a real Vapi export from a user's account would run end-to-end
      with no code change.
- [ ] `--provider vapi` runs the **existing** pipeline unchanged and produces the
      standard `data.json`.
- [ ] Absent provider fields → honest ABSENT detectors (no `len(text)`, no invented
      tokens); loud `IngestError` with source field path on unmappable input.
- [ ] `decision_kind` is inferred only by documented rules, flagged in provenance,
      and **never** feeds a measured D1 headline (§5) — proven by a test.
- [ ] One committed sample, explicitly labeled synthetic-schema-conformant (not real
      customer data).
- [ ] `docs/INGEST.md` documents the Vapi mapping table with cited Vapi field names.
- [ ] `uv run pytest` green incl. new adapter tests; full suite not regressed.
- [ ] `$0` — no provider/model call anywhere in code or acceptance path.

## 8. Test requirements

- Golden Vapi fixture → expected `IngestCall` (field-level assertions).
- Unmapped `endedReason` / tool status → `IngestError` with the offending value.
- Acoustic-absence → no tts/playback spans, D6/D7/D8 ABSENT.
- Inferred-`decision_kind` → flagged in provenance AND not counted as measured D1.
- CLI parity: `--provider vapi` output validates against the same pipeline the
  native format uses.

## 9. Risks

| Risk | Sev | Mitigation |
|---|---|---|
| Vapi schema differs from assumed field names | Med | Author the mapping against Vapi's *current* published docs; cite them; fixture-drive so a schema change fails a test, not production |
| Temptation to infer `decision_kind` broadly to light up detectors | High | §5 invariant + test; reviewer checks explicitly |
| Sample mistaken for real customer data | Med | Filename + in-file `"sample": true` + provenance note say "synthetic, schema-conformant" everywhere it surfaces |
| Token/acoustic gaps make the demo look empty | Low | That is the honest result; the ABSENT labels are the point, and Vapi's `costBreakdown` still yields a real cost decomposition |

## 10. Out of scope / future

- Retell, LiveKit, Bland, Pipecat adapters (same pattern, later).
- Live pull from a provider API (needs keys → would violate the $0 constraint here).
- Any re-tuning of detectors to fire more on provider data.

## 11. Handoff notes

- This PRD has no paid dependency and can start immediately; it feeds PRD 01's demo
  fleet, so landing it first is preferred.
- **Reviewer (Claude) will check:** the `decision_kind` honesty boundary (§5) above
  all, absent-field honesty, loud failure, provenance to the dashboard, no frozen-
  contract edits, and citations for the Vapi field names.
