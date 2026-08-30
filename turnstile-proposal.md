# Turnstile

**A margin profiler for voice AI agents.**

Every turn a voice agent takes is a toll gate. ASR charges by the audio minute, the LLM charges by the token, TTS charges by the character, and telephony charges for every second all three of them take. Turnstile measures the toll at every gate, finds the gates you're paying for and not using, and proves — by replay, not by suggestion — which ones you can remove without changing the outcome.

---

## 1. The problem nobody is measuring

The voice AI tooling market has converged on one question: *is the agent any good?* Coval, Hamming, Cekura, Roark, Cyara, Braintrust, and Observe.AI's own Agent Harness all answer some version of it — did it resolve, was it accurate, how fast did it respond, what was the word error rate.

Almost nobody answers the second question: **what did that cost, and did it need to?**

This was an engineering curiosity two years ago. It is a gross margin line today, for one reason: pricing in this category is drifting from per-seat toward per-resolution and per-minute. The moment a vendor charges for outcomes, cost-per-resolution *is* the margin. Every wasted token, every redundant retrieval, every extra turn comes directly out of it.

There is LLM observability (Langfuse, LangSmith, Braintrust) but it stops at the token and ignores the rest of the voice stack. There is contact-center analytics that reports AHT and containment but has no visibility into the model layer. Nothing spans both. Nothing tells a platform team: *your p90 conversation costs $1.34, of which $0.51 is recoverable, and here is the replay evidence.*

## 2. What Turnstile does

**Instruments** a running voice agent end to end with OpenTelemetry, capturing every stage of every turn: VAD, ASR, context assembly, LLM decision, tool calls, TTS, and telephony time.

**Prices** each span against a configurable unit-cost table, producing cost per turn, per conversation, and per *resolved* conversation.

**Detects** waste against an explicit taxonomy (section 4) rather than a vague "this looks expensive" heuristic.

**Proves** each finding by counterfactual replay: re-run the conversation from the suspect turn on the cheaper path and verify it reaches the same outcome. Report the cost delta, the latency delta, and the outcome-preservation rate.

**Reports** a ranked list of interventions denominated in annual dollars, each backed by replay evidence.

The output is not a suggestion. It is a claim with a confidence interval:

> Turn-3 intent routing uses the frontier model on 100% of calls. Replayed 340 conversations with a 200-token classifier at that turn: 96.2% reached identical resolution, mean cost fell 41%, p95 latency fell 380ms. The 13 divergent cases are listed below; 11 were ambiguous multi-intent openings.

## 3. Architecture

```
┌─ Layer 0 ── Agent Under Test ─────────────────────────────┐
│  Pipecat/LiveKit pipeline · 4 contact-center scenarios     │
│  ASR → LLM (tools) → TTS · barge-in · escalation path      │
└────────────────────────────────────────────────────────────┘
                          │ OTel spans
┌─ Layer 1 ── Trace Capture ────────────────────────────────┐
│  Span per stage. GenAI semantic conventions.               │
│  Decision spans record chosen path AND rejected candidates │
└────────────────────────────────────────────────────────────┘
┌─ Layer 2 ── Cost Model ───────────────────────────────────┐
│  Unit price table → cost per span, turn, conversation      │
│  Latency priced as telephony seconds ("silence tax")       │
└────────────────────────────────────────────────────────────┘
┌─ Layer 3 ── Waste Detectors ──────────────────────────────┐
│  Ten named waste classes, deterministic where possible     │
└────────────────────────────────────────────────────────────┘
┌─ Layer 4 ── Outcome Verdict (Resolution Ledger) ──────────┐
│  Evidence-linked resolution adjudication + calibration     │
└────────────────────────────────────────────────────────────┘
┌─ Layer 5 ── Counterfactual Replay ────────────────────────┐
│  Pin user side · replay from turn k under variant policy   │
│  Δcost · Δlatency · outcome-preservation rate              │
└────────────────────────────────────────────────────────────┘
┌─ Layer 6 ── Surface ──────────────────────────────────────┐
│  Cost flame graph · fleet view · ranked recoverable margin │
└────────────────────────────────────────────────────────────┘
```

**Why the verdict layer sits between the detectors and the replay engine:** every cost claim is conditional on "same outcome." If the outcome judge is not trustworthy, every number above it is decoration. This is the resolution ledger idea, folded in where it actually load-bears.

## 4. The waste taxonomy

This is the opinionated core. It is what makes Turnstile look like a team built it rather than a weekend hack.

| # | Class | What it is | Detection |
|---|-------|-----------|-----------|
| 1 | **Over-model** | Frontier model used for a routing, classification, or slot-extraction decision | Decision span with low output entropy / small output token count on an expensive model |
| 2 | **Context bloat** | Full history resent every turn; no pruning, no prefix caching | Input token growth curve vs. turn index; cache-hit ratio |
| 3 | **Redundant retrieval** | RAG or tool call whose answer already sits in context | Semantic overlap between retrieved chunk and prior context |
| 4 | **Turn inflation** | Agent takes 14 turns where the best path takes 8 | Turn count vs. per-intent golden path baseline |
| 5 | **Reprompt loops** | Agent asks the same question twice after a failed parse | Repeated slot-request spans within a conversation |
| 6 | **Dead tokens** | Generated text that never reaches the caller | LLM output tokens with no corresponding TTS span |
| 7 | **Barge-in waste** | TTS synthesized, billed, then discarded when the caller interrupts | TTS characters billed minus characters actually played |
| 8 | **Silence tax** | Telephony meter running during model latency | Sum of inter-span gaps × per-second telephony rate |
| 9 | **Escalation debt** | Everything spent before an inevitable human handoff | Full conversation cost on calls ending in escalation |
| 10 | **Tool thrash** | Repeated or redundant tool calls with equivalent arguments | Argument-hash collisions within a conversation |

Classes 6, 7, and 8 are voice-specific and do not exist in text-agent observability. **Barge-in waste is the demo moment** — you are literally paying to synthesize speech that nobody hears, and no tool on the market reports it.

## 5. Headline metrics

- **CPRC** — Cost per Resolved Conversation. The margin number. Decomposed by stage (ASR / LLM / TTS / telephony) and by intent.
- **Recoverable Margin %** — the share of CPRC that replay *proved* removable at ≥95% outcome preservation. The number he'll remember.
- **Waste Profile** — CPRC breakdown across the ten classes.
- **Cost-Quality Frontier** — for each config variant, plot resolution rate against CPRC. Release decisions live on this curve.

## 6. Why an Observe.AI CTO cares

**It completes the release decision they just shipped.** Agent Harness gates rollouts on quality via LLM-as-judge and phased release. Today a team can see that version 12 resolves 3% better than version 11. They cannot see that version 12 costs 40% more to run. That trade is currently unpriceable at the moment of decision. Turnstile adds the missing axis — a **cost gate** alongside the quality gate.

This is the framing that matters: it is not a competing product. It is the second axis of a decision surface they already built and already sell.

**It is denominated in their money, not their metrics.** At 1M calls/month, $0.30 of recovered CPRC is $3.6M a year. That is a sentence a CTO repeats to a CFO.

**It is defensible against the eval crowd.** Every vendor in that lane measures quality. None of them price the full stack, and none of them prove savings by replay.

## 7. Why Pranav is the credible person to build it

This is the strongest argument in the deck and it should be said out loud.

Two years of production work in edge inference optimization — TensorRT, OpenVINO, INT8 quantization — is *the same discipline*: making inference cheaper without losing accuracy, and proving the accuracy held. Turnstile is that discipline transplanted from embedded vision to voice agents.

Every other project idea on the table required inventing a track record. This one already has one.

## 8. The 48-hour build

**One honest note before the plan:** 48 hours of wall clock is roughly 30 hours of good work with sleep, and quality collapses past hour 20 without it. The plan below is scoped for ~30 productive hours. The buffer is real and will be consumed.

### Hour 0–1: Freeze the trace schema

Do this first, alone, before spawning any agent. Every parallel workstream reads and writes this schema. If it changes at hour 20, everything breaks. Define span types, required attributes, cost fields, and the conversation manifest format. Write it down. Freeze it.

### Workstream split (parallel coding agents)

| Agent | Owns | Deliverable |
|-------|------|-------------|
| A | Voice agent + 4 scenarios + synthetic caller harness | Runnable agent generating real audio calls |
| B | OTel instrumentation + cost model | Priced traces conforming to schema |
| C | Waste detectors (10 classes) | Detector suite + findings JSON |
| D | Replay engine + outcome verdict | Δcost/Δoutcome experiment runner |
| E | Dashboard + flame graph | Static surface reading findings JSON |

You integrate. Nobody but you touches the schema.

### Timeline

- **H0–4** — Schema freeze. Agent A stands up the pipeline: Pipecat or LiveKit Agents, Deepgram or faster-whisper ASR, a tool-calling LLM, a TTS provider. Four scenarios: order status, identity verification + refund, plan change with an upsell branch, and one designed to escalate.
- **H4–10** — Agent B wires OTel and the price table. Agent A builds the synthetic caller: LLM-driven personas rendered through TTS and fed back through ASR, so the traffic is genuinely acoustic rather than a text shortcut. Include accents, background noise, interruptions, and one caller who changes their mind mid-call. Generate 250–400 calls.
- **H10–18** — Agent C builds detectors. Start with the five that are fully deterministic (2, 6, 7, 8, 10). Classes 1, 3, 4, 5, 9 need judgment and come second.
- **H18–26** — Agent D builds replay. **This is the hardest block and the one that makes or breaks the project.** Protect it. See risks below.
- **H26–34** — Run the experiment matrix. Four to six config variants across the corpus. This is where you get real numbers. Do not skip ahead to the dashboard before you have them.
- **H34–42** — Agent E's surface. Hero view is the cost flame graph for a single call, second is the fleet-level recoverable-margin ranking.
- **H42–46** — README, method note, limitations, and a four-minute recorded walkthrough.
- **H46–48** — Buffer.

### Cut list, in order

If you fall behind, sacrifice in this sequence: dashboard polish → detector classes 1/3/5 → number of scenarios (four to two) → corpus size (400 to 150). **Never cut the replay engine or the calibration of the outcome judge.** Those two are the entire credibility of the project.

## 9. Risks and mitigations

**Replay determinism.** Re-running a conversation is genuinely hard because the agent's output changes what the caller says next. Mitigation: pin the caller side. Use the recorded caller audio and replay only the agent's decision path from turn *k*, with tool responses cached and served from the original trace. This constrains what you can claim — say so in the write-up. Full open-loop replay with a live synthetic caller is the stretch goal, not the baseline.

**Outcome judge trust.** Hand-label 60 conversations before writing the judge. Report agreement. An uncalibrated judge invalidates every dollar figure downstream.

**Cost model accuracy.** Pull live published rates at build time and keep them in one config file with a dated source comment. Do not hardcode prices into logic. Expect to be challenged on them in the meeting.

**Synthetic traffic is not production traffic.** State it plainly and first. The defensible claim is "the method finds these classes of waste and quantifies them," not "your fleet wastes 41%."

## 10. What to walk into the room with

1. Four-minute recorded demo. Live demos fail on someone else's wifi.
2. One printed page: the CPRC decomposition and the recoverable-margin table.
3. The limitations slide, presented before he asks.
4. Memorized: corpus size, judge agreement, outcome-preservation rate, biggest single recoverable line item, and one annualized dollar figure with its assumptions stated.
5. The Agent Harness framing (section 6, first point) as the opening sentence.

Do not call it a product. Call it a profiler.

---

### Naming alternatives
Turnstile · Marginal · Larynx · Meter · Waveform
