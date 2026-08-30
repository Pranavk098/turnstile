# Turnstile — Engineering PRD v1.0

**A margin profiler for voice AI agents.**
Measures what every turn actually costs across ASR, LLM, TTS, tools, and telephony. Identifies waste against an explicit taxonomy. Proves each finding by counterfactual replay rather than asserting it.

**Status:** contract-frozen. Sections 3, 4, and 5 are binding interfaces. No implementing agent may modify them.

---

# Part I — Product

## 1. Thesis

Voice AI pricing is drifting from per-seat toward per-resolution and per-minute. The moment a vendor charges for outcomes, **cost-per-resolution is gross margin**. Yet the entire tooling market measures quality and ignores cost.

LLM observability (Langfuse, LangSmith, Braintrust) stops at the token and never sees ASR, TTS, or telephony. Contact-center analytics reports AHT and containment and never sees the model layer. Voice eval tools (Coval, Hamming, Cekura, Roark, Cyara) measure whether the agent was good, never what it cost to be good.

Nothing spans both layers. Nothing answers: *your p90 conversation costs $1.34, $0.51 of that is recoverable, and here is the replay evidence.*

## 2. Non-goals

Turnstile is **not**: a quality eval framework, a prompt optimizer, an agent-building framework, a real-time cost governor, or an APM. It reads traces and produces evidence. It does not sit in the request path.

Anything that improves quality without a cost claim attached is out of scope.

---

# Part II — Frozen Contracts

Everything in Part II is a binding interface. It is authored once, before any implementation agent is spawned, and versioned. Changing it mid-build invalidates every parallel workstream.

## 3. Trace schema

OpenTelemetry-compatible, GenAI semantic conventions where they exist, `turnstile.*` namespace where they don't.

### 3.1 Span hierarchy

```
conversation                        (root)
└── turn                            (one per caller-agent exchange)
    ├── vad.segment
    ├── asr.transcribe
    ├── context.assemble
    ├── llm.decide                  (may repeat: planning, reflection, retry)
    ├── tool.call                   (0..n)
    ├── tts.synthesize
    └── audio.playback
telephony.leg                       (spans whole conversation, sibling of root)
```

### 3.2 Required attributes

**`conversation`**
```jsonc
{
  "conversation_id":   "uuid",
  "agent_version":     "string",       // config hash of agent under test
  "scenario_id":       "string",
  "started_at":        "rfc3339",
  "ended_at":          "rfc3339",
  "end_reason":        "caller_hangup | agent_hangup | escalated | timeout | error",
  "turnstile.schema_version": "1.0"
}
```

**`turn`**
```jsonc
{
  "turn_index":        0,
  "speaker_first":     "caller | agent",
  "wall_start_ms":     0,
  "wall_end_ms":       0,
  "barge_in":          false          // caller interrupted agent during this turn
}
```

**`asr.transcribe`**
```jsonc
{
  "gen_ai.system":            "deepgram",
  "gen_ai.request.model":     "nova-3",
  "turnstile.audio_seconds":  4.82,
  "turnstile.is_streaming":   true,
  "turnstile.transcript":     "string",
  "turnstile.confidence":     0.94
}
```

**`context.assemble`**
```jsonc
{
  "turnstile.context_tokens":        3840,
  "turnstile.history_tokens":        2900,
  "turnstile.system_tokens":         620,
  "turnstile.retrieved_tokens":      320,
  "turnstile.retrieved_doc_ids":     ["kb_412"],
  "turnstile.pruning_strategy":      "none | window | summarize | semantic"
}
```

**`llm.decide`** — the most important span. Every field is load-bearing for a detector.
```jsonc
{
  "gen_ai.system":                    "anthropic",
  "gen_ai.request.model":             "claude-sonnet-4-6",
  "gen_ai.usage.input_tokens":        3840,
  "gen_ai.usage.output_tokens":       28,
  "turnstile.cache_read_tokens":      0,
  "turnstile.cache_write_tokens":     0,
  "turnstile.reasoning_tokens":       0,
  "turnstile.decision_kind":          "route | slot_fill | tool_select | compose | escalate_check",
  "turnstile.decision_chosen":        "lookup_order",
  "turnstile.decision_candidates":    ["lookup_order","verify_identity","escalate"],
  "turnstile.output_text":            "string",
  "turnstile.latency_ms":             820,
  "turnstile.retry_of":               null      // span_id if this is a retry
}
```

`decision_kind` is mandatory and must be emitted by the agent, not inferred. Detector 1 is unbuildable without it.

**`tool.call`**
```jsonc
{
  "turnstile.tool_name":       "lookup_order",
  "turnstile.args_hash":       "sha256:...",   // normalized: sorted keys, lowercased values
  "turnstile.args_json":       "{...}",
  "turnstile.result_hash":     "sha256:...",
  "turnstile.latency_ms":      340,
  "turnstile.cost_usd":        0.0,            // external API cost if any
  "turnstile.tool_kind":       "retrieval | mutation | lookup | handoff"
}
```

**`tts.synthesize`**
```jsonc
{
  "gen_ai.system":                  "cartesia",
  "turnstile.chars_synthesized":    184,
  "turnstile.audio_seconds_generated": 11.2,
  "turnstile.text":                 "string"
}
```

**`audio.playback`** — required for Detector 7. Most stacks do not emit this. Instrumenting it is a Layer 0 deliverable.
```jsonc
{
  "turnstile.chars_played":         61,
  "turnstile.audio_seconds_played": 3.8,
  "turnstile.truncated_by":         "barge_in | hangup | null"
}
```

**`telephony.leg`**
```jsonc
{
  "turnstile.provider":       "twilio",
  "turnstile.direction":      "inbound | outbound",
  "turnstile.billable_seconds": 184
}
```

### 3.3 Golden fixtures

Twenty hand-authored traces conforming to this schema, committed at `fixtures/golden/`, each engineered to trigger a specific detector. **These are what unlock parallel development** — detectors, verdict, replay, and dashboard all develop against fixtures and never wait on the live agent.

Required fixtures: one clean baseline, one per detector class (10), three multi-waste, two escalation, one abandoned, one false-resolve, two edge (single-turn, 40-turn).

## 4. Cost model

### 4.1 Price table

Single config file, `pricing/rates.yaml`. Every entry dated with a source URL comment. Never hardcode a rate into logic.

```yaml
asr:
  deepgram/nova-3:      { unit: audio_minute, rate: 0.0043 }
llm:
  anthropic/claude-sonnet-4-6:
    { unit: mtok, input: 3.00, output: 15.00, cache_read: 0.30, cache_write: 3.75 }
tts:
  cartesia/sonic-2:     { unit: char_1k, rate: 0.025 }
telephony:
  twilio/pstn_inbound:  { unit: minute, rate: 0.0085 }
```

### 4.2 Formulas

```
cost_asr   = audio_seconds / 60 × rate_per_minute

cost_llm   = (input_tokens − cache_read_tokens)/1e6 × rate_in
           + cache_read_tokens/1e6            × rate_cache_read
           + cache_write_tokens/1e6           × rate_cache_write
           + (output_tokens + reasoning_tokens)/1e6 × rate_out

cost_tts   = chars_synthesized / 1000 × rate_per_1k     # synthesized, NOT played

cost_tel   = billable_seconds / 60 × rate_per_minute     # attributed to turns
                                                          # pro-rata by wall time

cost_turn  = Σ(child span costs) + attributed telephony
cost_conv  = Σ(cost_turn)
```

`cost_tts` uses **synthesized** rather than played characters deliberately. The gap between them is Detector 7 and it is real money.

### 4.3 Headline metrics

```
CPRC_naive  = Σ cost(conversations where verdict = RESOLVED) / count(RESOLVED)

CPRC_loaded = Σ cost(ALL conversations) / count(RESOLVED)
```

**`CPRC_loaded` is the real margin number.** You pay for the calls that fail too, and their cost is carried by the ones that succeed. Report both; lead with loaded. Most vendors quote naive because it flatters them. Saying this out loud in the room is a credibility move.

```
Recoverable Margin % = Σ proven_savings / CPRC_loaded
```
where `proven_savings` counts only interventions where replay achieved outcome-preservation ≥ 0.95 with the lower bound of the bootstrap CI still positive.

## 5. Module interfaces

Every package exposes exactly one entry point. Agents implement behind these signatures and may not change them.

```python
# packages/pricing
def price_trace(trace: Trace, rates: RateTable) -> PricedTrace: ...

# packages/verdict
def adjudicate(trace: PricedTrace) -> Verdict: ...
# Verdict = { label, confidence, evidence[], turn_of_no_return }

# packages/detectors
def detect(trace: PricedTrace, verdict: Verdict, baselines: Baselines) -> list[Finding]: ...
# Finding = { class_id, turn_index, span_id, waste_usd, confidence,
#             proposed_variant: VariantSpec, evidence: dict }

# packages/replay
def replay(trace: PricedTrace, variant: VariantSpec, from_turn: int) -> Trial: ...
def experiment(traces: list, variant: VariantSpec) -> ExperimentResult: ...
# ExperimentResult = { n, outcome_preservation_rate, delta_cost_mean,
#                      delta_cost_ci95, delta_latency_p50, delta_latency_p95,
#                      divergent_exemplars[] }

# packages/dashboard  — consumes findings.json + experiments.json only
```

---

# Part III — Detection

## 6. Waste taxonomy

Ten classes. Classes 6, 7, and 8 do not exist in text-agent observability and are the differentiator.

| # | Class | Detection rule | Waste calculation |
|---|-------|----------------|-------------------|
| 1 | **Over-model** | `decision_kind ∈ {route, slot_fill, escalate_check}` AND `output_tokens < 32` AND model tier = frontier | `cost_llm − cost_llm(cheapest tier serving same decision)` |
| 2 | **Context bloat** | Linear fit of `input_tokens ~ turn_index`, slope > 400 tok/turn AND `cache_read_tokens / input_tokens < 0.5` | tokens above windowed-context baseline × rate_in |
| 3 | **Redundant retrieval** | `tool_kind = retrieval` AND (`retrieved_doc_ids ∩ prior_context_doc_ids ≠ ∅` OR cosine(chunk, context) > 0.85) | tool cost + `retrieved_tokens × rate_in` |
| 4 | **Turn inflation** | `turns_to_resolution > p75(intent baseline)` | `(turns − p50_baseline) × mean_cost_per_turn` |
| 5 | **Reprompt loop** | ≥2 `llm.decide` with same `decision_kind` targeting same slot, no fill between | cost of all turns after the first reprompt |
| 6 | **Dead tokens** | `output_text` with no matching `tts.synthesize`, or synthesized text is a strict substring | unmatched `output_tokens × rate_out` |
| 7 | **Barge-in waste** | `chars_synthesized > chars_played` | `(chars_synth − chars_played)/1000 × rate_tts` + attributable LLM output tokens |
| 8 | **Silence tax** | Inter-span gaps > 200ms with no audio flowing | `Σ gap_seconds × telephony_rate_per_second`, split by cause: model / tool / ASR endpointing |
| 9 | **Escalation debt** | `verdict = ESCALATED` AND escalation classifier ≥ 0.9 at turn `t < escalation_turn` | full cost of turns `t..end` |
| 10 | **Tool thrash** | Duplicate `args_hash` for same `tool_name` within conversation | cost of duplicate calls + their turns |

**Detector 7 is the demo moment.** You are billed for speech the caller interrupted and never heard. It is trivially detectable, entirely voice-specific, and no product on the market reports it.

**Detector 9 is the most commercially interesting.** "Escalation was predictable at turn 3 with 0.94 confidence. You spent nine more turns and $0.41 before handing off. Across the corpus that is $88k/year." That is a product feature, not a metric.

Every `Finding` must carry a `proposed_variant` that the replay engine can execute. A detector that cannot propose a testable alternative is not allowed to emit a finding.

## 7. Verdict layer (Resolution Ledger)

Every cost claim is conditional on "same outcome." If the judge is untrustworthy, every number above it is decoration.

**Labels:** `RESOLVED`, `PARTIALLY_RESOLVED`, `UNRESOLVED`, `ESCALATED`, `ABANDONED`, `MISROUTED`, `FALSE_RESOLVE`.

`FALSE_RESOLVE` — agent asserts completion but the terminal tool state contradicts it — is the most expensive failure in the taxonomy and the one LLM judges miss most often. It gets its own detector in the report.

**Evidence sources, in precedence order:**
1. Terminal tool state (deterministic; a refund either executed or did not)
2. Required-slot completion against scenario definition
3. Caller confirmation utterance in final two turns
4. Absence of escalation span
5. LLM judgment (lowest weight, used only to break ties)

**Calibration is mandatory.** Hand-label 60 conversations *before* writing the judge. Report agreement (Cohen's κ) and expected calibration error. Ship the confusion matrix in the README. An uncalibrated judge invalidates every dollar figure downstream, and this is the first thing a CTO will probe.

**`turn_of_no_return`:** the earliest turn at which the final verdict was already determined. Feeds Detector 9.

## 8. Counterfactual replay

The credibility engine. Without it, findings are opinions.

### 8.1 Modes

**Pinned replay (baseline, must ship).** Caller audio fixed from the original trace. Tool responses served from the trace cache by `args_hash`. Replay agent decisions from turn *k* under the variant policy.

Divergence handling: if the variant agent's utterance at turn *k* has semantic similarity < 0.75 to the original, the conversation has forked and pinned caller audio is no longer valid. Mark the trial `DIVERGENT` and route to open-loop if available, otherwise exclude and report the exclusion rate. **Report the exclusion rate prominently** — a variant that forks 40% of conversations has a much weaker claim than one that forks 3%.

**Open-loop replay (stretch).** Synthetic caller LLM resumes from turn *k* with the original persona and goal, rendered through TTS and back through ASR. Higher validity, much higher variance, needs n≥3 per trace.

### 8.2 Variant space

```jsonc
{
  "model_routing":    { "route": "haiku", "compose": "sonnet" },
  "context_strategy": "window:8 | summarize:2000 | semantic:0.7",
  "prefix_caching":   true,
  "retrieval_policy": "off | threshold:0.8 | always",
  "tts_chunking":     "sentence | full",
  "escalation_policy":"threshold:0.85",
  "tool_batching":    true
}
```

### 8.3 Statistical requirements

Non-negotiable, because these are the numbers he will challenge:

- n ≥ 200 traces per variant
- Bootstrap 95% CI on Δcost, 10,000 resamples
- Outcome preservation reported with Wilson score interval
- A variant only enters "proven savings" if the CI lower bound on savings is > 0 **and** preservation ≥ 0.95
- Every divergent case listed and categorized, not hidden

---

# Part IV — Execution

## 9. Repository

```
turnstile/
├── packages/
│   ├── schema/          # frozen contracts, codegen types, validators
│   ├── agent/           # Layer 0: agent under test
│   ├── caller/          # synthetic caller harness
│   ├── otel/            # instrumentation shims
│   ├── pricing/         # rate table + cost engine
│   ├── verdict/         # resolution ledger
│   ├── detectors/       # ten classes
│   ├── replay/          # counterfactual engine
│   └── dashboard/       # static surface
├── fixtures/golden/     # 20 hand-authored traces
├── corpus/              # generated call traces
├── experiments/         # variant results
└── docs/
    ├── PRD.md
    ├── METHOD.md
    └── LIMITATIONS.md
```

## 10. Parallel agent delegation

### 10.1 The rule that makes this work

**Fixture-driven parallelism.** Every downstream package develops against the 20 golden fixtures, never against another agent's live output. Detectors do not wait for the voice agent. Replay does not wait for detectors. The dashboard does not wait for anything.

This is the single decision that turns a 5-day serial build into a 2-day parallel one. It only works if the schema is frozen and the fixtures exist *before* Wave 1 spawns.

### 10.2 Hard constraints on every agent

- Only the human edits `packages/schema/` and `fixtures/golden/`.
- No agent edits another agent's package. Cross-package needs go through the human as an interface request.
- Every PR must pass `make contract-test` (schema validation against fixtures).
- Every package ships its own unit tests. An agent that reports "done" without a passing test suite is not done.
- No agent invents a rate, threshold, or constant. Constants live in config with a dated source.

### 10.3 Waves

**Wave 0 — human only, ~2h.** Write `packages/schema/`. Author the 20 golden fixtures by hand. Write `rates.yaml`. Stand up CI with `contract-test`. Nothing else starts until this lands. This is the highest-leverage two hours in the project.

**Wave 1 — 5 parallel agents.**

| Agent | Package | Tool fit | Acceptance criteria |
|-------|---------|----------|---------------------|
| **A1** | `agent/` + `otel/` | Claude Code (integration-heavy, real APIs) | Runs a full call; emits schema-valid trace including `audio.playback` |
| **A2** | `pricing/` | OpenCode (mechanical, well-specified) | Prices all 20 fixtures; unit tests cover every formula branch |
| **A3** | `detectors/` classes 2,6,7,8,10 | OpenCode (deterministic rules) | Each fires on its fixture, silent on baseline; zero false positives on clean fixture |
| **A4** | `verdict/` | Claude Code (judgment-heavy) | κ ≥ 0.75 vs. hand labels; calibration curve committed |
| **A5** | `dashboard/` | Any | Renders findings.json + experiments.json; cost flame graph works on fixtures |

**Wave 2 — 3 agents, spawned at integration checkpoint 1.**

| Agent | Package | Tool fit | Depends on |
|-------|---------|----------|------------|
| **B1** | `replay/` | Claude Code (hardest module — give it the strongest tool) | schema + pricing + verdict |
| **B2** | `caller/` + corpus generation | Claude Code | agent/ |
| **B3** | `detectors/` classes 1,3,4,5,9 | Claude Code (need verdict + baselines) | verdict, corpus |

**Wave 3 — 2 agents.** Experiment runner and statistics (`experiments/`), and documentation (`METHOD.md`, `LIMITATIONS.md`, README with all numbers).

### 10.4 The real constraint

It is not agent count. It is **your review bandwidth.** One person can meaningfully integrate about five parallel streams. Past that you are rubber-stamping code you have not read, and rubber-stamped code is where the demo dies at hour 40.

Run five, not twelve. Merge at fixed checkpoints (H10, H18, H26, H34), not continuously. Between checkpoints, agents work; at checkpoints, you read.

### 10.5 Agent brief template

Every spawn gets exactly this, filled in. Vague briefs are the leading cause of parallel-agent garbage.

```
MISSION:      one sentence
PACKAGE:      packages/<name>/  — you may edit nothing outside this
CONTRACT:     paste the exact function signature from §5
INPUTS:       fixtures/golden/*.json (schema v1.0, see packages/schema/)
OUTPUT:       exact JSON shape, with a worked example
ACCEPTANCE:   specific, runnable — "make test-<pkg> passes and
              detector fires on fixture 07, silent on fixture 00"
FORBIDDEN:    editing schema/, editing other packages, inventing
              constants, adding dependencies without asking
WHEN STUCK:   stop and report; do not work around the contract
```

## 11. Timeline

| Block | Wall clock | Work |
|-------|-----------|------|
| W0 | H0–2 | Schema, fixtures, rates, CI. Human alone. |
| W1 | H2–10 | Five agents in parallel. **Checkpoint 1 at H10.** |
| W2 | H10–20 | Replay, caller, judgment detectors. Corpus generation runs in background. **Checkpoint 2 at H18.** |
| — | H20–28 | **Sleep.** Non-negotiable. See §13. |
| W2b | H28–34 | Integrate. Run the experiment matrix — 6 variants × 250 traces. **Checkpoint 3 at H34.** |
| W3 | H34–42 | Dashboard against real data. Documentation. Numbers memorized. |
| — | H42–46 | Record the four-minute demo. Write LIMITATIONS.md. |
| — | H46–48 | Buffer. It will be consumed. |

**Cut list, strictly in order:** dashboard polish → detectors 1/3/5 → open-loop replay → scenarios 4→2 → corpus 400→150. **Never cut pinned replay or verdict calibration.** Those two are the entire credibility of the project.

## 12. Risk register

| Risk | Severity | Mitigation |
|------|----------|------------|
| `audio.playback` not exposed by the voice framework | **Critical** — kills Detector 7 | Validate in H0–2, before Wave 1. If unavailable, instrument the audio sink directly or switch framework. Do not discover this at H30. |
| Replay divergence rate too high to claim anything | High | Pin tool responses by `args_hash`; report exclusion rate honestly; fall back to per-turn cost claims rather than whole-conversation ones |
| Verdict judge poorly calibrated | High | 60 hand labels *first*; if κ < 0.7, simplify to deterministic tool-state checks only |
| Synthetic traffic ≠ production traffic | Medium | State it first and plainly. Claim is "this method finds and quantifies these waste classes," never "your fleet wastes 41%" |
| Rate table stale or wrong | Medium | Dated sources in config; expect to be challenged; know which rates you pulled and when |
| Parallel agents produce incoherent code | Medium | Contract-first + fixtures + checkpoint merges + five-stream cap |

## 13. Two honest notes

**On 48 nonstop hours.** It produces roughly 30 hours of usable work and then a quality cliff. The schedule above bakes in an 8-hour sleep at H20 because the alternative is spending H40–46 debugging something you broke at H32 while exhausted. The demo is at stake, not your stamina.

**On what this proves.** Turnstile on synthetic traffic does not prove Observe.AI's fleet wastes money. It proves you can build the instrument, that the waste classes are real and measurable, and that you know the difference between a measured claim and a suggestion. That is the entire point. A CTO does not need you to have already audited his fleet. He needs to believe you could.

---

## Appendix A — Demo script, four minutes

1. **0:00** One conversation, cost flame graph. "This call cost $1.34. Here is where it went."
2. **0:45** Zoom to Detector 7. "Nineteen cents of that was speech we synthesized, billed, and the caller interrupted before hearing. Nobody reports this."
3. **1:30** Fleet view. CPRC_loaded vs. naive. "Most vendors quote the left number. The right one is your actual margin."
4. **2:15** Detector 9. "Escalation was predictable at turn 3. We spent nine more turns getting there."
5. **3:00** Replay evidence. "We did not suggest the cheaper router. We replayed 340 conversations on it. 96.2% identical outcome, 41% cost reduction, here are the thirteen that broke."
6. **3:40** Limitations, unprompted.

## Appendix B — Numbers to memorize

Corpus size · scenario count · verdict κ and ECE · replay divergence rate · outcome-preservation rate per variant · CPRC_loaded and its decomposition · largest single recoverable line item · one annualized figure with assumptions stated aloud.
