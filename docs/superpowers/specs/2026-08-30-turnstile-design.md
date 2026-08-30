# Turnstile — Build Design Spec

**Date:** 2026-08-30
**Status:** Draft for review
**Authoritative contracts:** `turnstile-prd.md` §3 (trace schema), §4 (cost model), §5 (module interfaces) are **frozen** and take precedence over this document. This spec records the *build decisions* and *execution plan* layered on top of them. Where this spec and the PRD disagree on a contract, the PRD wins.

---

## 1. What we are building

A **margin profiler for voice AI agents.** It instruments a voice call end-to-end (VAD → ASR → context → LLM → tools → TTS → telephony), prices every span against a config-driven rate table, detects ten named waste classes, adjudicates whether the call was actually *resolved*, and **proves** each savings claim by counterfactually replaying the call on a cheaper path.

The output is not a suggestion — it is a claim with a confidence interval, backed by replay evidence.

**Non-goals** (from PRD §2): not a quality-eval framework, prompt optimizer, agent-building framework, real-time cost governor, or APM. Turnstile reads traces and produces evidence. It does not sit in the request path. Anything that improves quality without a cost claim attached is out of scope.

---

## 2. Decisions made in brainstorming (2026-08-30)

These are the choices that adapt the PRD to the real execution environment. They do **not** modify any frozen contract.

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Goal: live 48h-style sprint.** Optimize for a credible 4-minute demo + memorized numbers. Honor the PRD cut list under pressure. | User selection. |
| D2 | **Audio stack = Path B: local models.** faster-whisper (ASR) + Piper/Kokoro (TTS) + **simulated** telephony leg. Real acoustic audio, zero external audio cost, offline-demoable, Windows-friendlier. | Cost model is config-driven (rates.yaml), so pricing is real regardless of who generates the audio. Local audio also lets us **control the audio sink directly**, guaranteeing `audio.playback` capture — the Detector 7 kill-risk (PRD §12). |
| D3 | **Agent-under-test runs on OpenAI**, funded by user's ~$150 OpenAI credit. Tier ladder: `gpt-5` (frontier/compose) → `gpt-5-mini` → `gpt-5-nano` (cheap classifier / replay target). | Provider-agnostic schema (`gen_ai.system` + `gen_ai.request.model`) makes this a config change. OpenAI's frontier→nano gradient is a *cleaner* tier ladder for Detector 1 (over-model) and the `model_routing` replay variant than a cross-provider setup, all on one invoice. **Anthropic API spend → $0.** |
| D4 | **Synthetic caller runs on `gpt-5-nano`.** | Pennies; keeps all runtime on the single OpenAI credit. |
| D5 | **Execution = parallel Claude Code subagents + one Zen mechanical-lane agent.** I (this Opus session) own Wave 0 and the judgment-heavy packages and act as integrator; a Zen agent (DeepSeek V4 Flash) owns the deterministic, fixture-gated packages. | Honors PRD §10.3 tool-fit column ("mechanical, well-specified" → cheap tool; "hardest module" → strongest tool). Fixture + `contract-test` gating makes weak-model output *verifiable*, so cheap parallelism is safe. |
| D6 | **Telephony is simulated, not real Twilio.** We emit `telephony.leg` spans with realistic `billable_seconds` computed from wall-clock, priced via rates.yaml. No PSTN, no phone numbers. | Zero demo value in real PSTN; adds cost and Windows pain. The silence-tax / telephony math is identical whether the seconds are billed by Twilio or computed locally. |
| D7 | **Voice-agent package (`agent/` + `otel/`) developed under WSL2**; all pure-Python analysis packages run in native Windows. | Pipecat / PyAudio / whisper are painful in native Windows. |

### 2.1 Instrumentation notes forced by D3 (no contract change)

- OpenAI prompt caching is **automatic**. Map OpenAI's cached-input tokens → `turnstile.cache_read_tokens`; set `turnstile.cache_write_tokens = 0`. Detector 2 (context bloat, uses `cache_read/input` ratio) is unaffected.
- Add dated OpenAI rows to `pricing/rates.yaml` (`gpt-5`, `gpt-5-mini`, `gpt-5-nano` with input / cached-input / output rates and a source URL comment).
- The `model_routing` variant example in PRD §8.2 (`{route: haiku, compose: sonnet}`) is illustrative; our concrete variants use OpenAI tiers, e.g. `{route: gpt-5-nano, compose: gpt-5}`.

---

## 3. Cost model for the build itself (three buckets)

| Bucket | What | Estimate | Funded by |
|--------|------|----------|-----------|
| 1. Zen dev | cheap agents coding the mechanical lane (`pricing/`, deterministic detectors, `dashboard/`) | ~$5–10 (DeepSeek V4 Flash @ $0.14/$0.28 per 1M) | user's $20 Zen |
| 2. Claude dev | this Opus session: Wave 0 + `agent`/`otel`, `verdict`, `replay`, integration | usage-window only (subscription) | user's Claude plan |
| 3. Runtime | agent-under-test + synthetic caller + replay experiment matrix | ~$60–130 (GPT-5 agent, nano caller/variants) | user's $150 OpenAI credit |

**Net new out-of-pocket dollars: ~$0.** No Anthropic API spend.

---

## 4. Architecture (PRD §3 / proposal §3)

```
Layer 0  Agent Under Test        Pipecat pipeline · 4 scenarios · barge-in · escalation
Layer 1  Trace Capture           OTel spans, GenAI conventions, decision spans record chosen + rejected
Layer 2  Cost Model              rate table → cost per span/turn/conversation; latency priced as telephony
Layer 3  Waste Detectors         10 named classes, deterministic where possible
Layer 4  Outcome Verdict         Resolution Ledger — evidence-linked adjudication + calibration
Layer 5  Counterfactual Replay   pin caller side · replay from turn k under variant · Δcost/Δlatency/preservation
Layer 6  Surface                 cost flame graph · fleet view · ranked recoverable margin
```

The verdict layer sits **between** detectors and replay because every cost claim is conditional on "same outcome." An untrustworthy judge makes every number above it decoration.

---

## 5. Frozen contracts (reference — see PRD for the binding text)

These are **authored and owned only by this Opus session + the human** (PRD §10.2). No parallel agent may edit `packages/schema/` or `fixtures/golden/`.

- **Trace schema** — PRD §3. OTel-compatible, GenAI conventions, `turnstile.*` namespace. Span hierarchy: `conversation → turn → {vad, asr, context.assemble, llm.decide, tool.call, tts.synthesize, audio.playback}`, plus sibling `telephony.leg`. `audio.playback` and `llm.decide.decision_kind` are mandatory and load-bearing.
- **Cost model** — PRD §4. `pricing/rates.yaml` is the single source of rates; every rate dated with a source URL. Formulas for ASR/LLM/TTS/telephony are fixed. `cost_tts` uses **synthesized** (not played) characters deliberately — the gap is Detector 7.
- **Headline metrics** — PRD §4.3. `CPRC_naive`, `CPRC_loaded` (lead with loaded), `Recoverable Margin %`.
- **Module interfaces** — PRD §5. One entry point per package: `price_trace`, `adjudicate`, `detect`, `replay` / `experiment`. Agents implement behind these signatures and may not change them.

### 5.1 Golden fixtures (the parallelism unlock — PRD §3.3)

Twenty hand-authored, schema-valid traces at `fixtures/golden/`, each engineered to trigger a specific detector. **Written in Wave 0, before any agent spawns.** Required set: 1 clean baseline, 1 per detector class (10), 3 multi-waste, 2 escalation, 1 abandoned, 1 false-resolve, 2 edge (single-turn, 40-turn). These are what let detectors/verdict/replay/dashboard all develop in parallel without waiting on the live agent.

---

## 6. Waste taxonomy (PRD §6)

Ten classes; **6, 7, 8 are voice-specific and the differentiator.** Each `Finding` must carry a `proposed_variant` the replay engine can execute — a detector that cannot propose a testable alternative may not emit a finding.

1. Over-model · 2. Context bloat · 3. Redundant retrieval · 4. Turn inflation · 5. Reprompt loop · 6. **Dead tokens** · 7. **Barge-in waste** (the demo moment) · 8. **Silence tax** · 9. **Escalation debt** (most commercially interesting) · 10. Tool thrash.

Detection rules and waste calculations are fixed in PRD §6.

---

## 7. Verdict layer — Resolution Ledger (PRD §7)

Labels: `RESOLVED`, `PARTIALLY_RESOLVED`, `UNRESOLVED`, `ESCALATED`, `ABANDONED`, `MISROUTED`, `FALSE_RESOLVE`.

Evidence precedence: (1) terminal tool state → (2) required-slot completion → (3) caller confirmation utterance → (4) absence of escalation → (5) LLM judgment (tie-break only).

**Calibration is mandatory and non-negotiable.** Hand-label 60 conversations *before* writing the judge. Report Cohen's κ and expected calibration error; ship the confusion matrix in the README. Target **κ ≥ 0.75**. If κ < 0.7, fall back to deterministic tool-state checks only. `turn_of_no_return` feeds Detector 9.

---

## 8. Counterfactual replay (PRD §8)

**Pinned replay (baseline, must ship):** caller audio fixed from the trace; tool responses served from the trace cache by `args_hash`; replay agent decisions from turn *k* under the variant policy. If a variant utterance at turn *k* has semantic similarity < 0.75 to the original, mark the trial `DIVERGENT` and **report the exclusion rate prominently**.

**Open-loop replay (stretch):** synthetic caller resumes from turn *k*, rendered through TTS/ASR. On the cut list.

**Statistical requirements (non-negotiable):** n ≥ 200 traces/variant; bootstrap 95% CI on Δcost (10,000 resamples); outcome preservation with Wilson score interval; a variant enters "proven savings" only if the CI lower bound on savings > 0 **and** preservation ≥ 0.95; every divergent case listed and categorized.

Variant space per PRD §8.2 (model_routing, context_strategy, prefix_caching, retrieval_policy, tts_chunking, escalation_policy, tool_batching), with model routing bound to OpenAI tiers (D3).

---

## 9. Repository layout (PRD §9)

```
turnstile/
├── packages/
│   ├── schema/      # frozen contracts, codegen types, validators   [human/Opus only]
│   ├── agent/       # Layer 0: agent under test                     [Opus]
│   ├── caller/      # synthetic caller harness                      [Opus, Wave 2]
│   ├── otel/        # instrumentation shims                         [Opus]
│   ├── pricing/     # rate table + cost engine                      [Zen]
│   ├── verdict/     # resolution ledger                             [Opus]
│   ├── detectors/   # ten classes                                   [Zen: 2,6,7,8,10 · Opus: 1,3,4,5,9]
│   ├── replay/      # counterfactual engine                         [Opus, Wave 2]
│   └── dashboard/   # static surface                                [Zen]
├── fixtures/golden/ # 20 hand-authored traces                       [human/Opus only]
├── corpus/          # generated call traces
├── experiments/     # variant results
├── pricing/rates.yaml
└── docs/{PRD.md, METHOD.md, LIMITATIONS.md}
```

**Toolchain:** Python monorepo managed with `uv`. `pytest` per package. A top-level `make contract-test` validates every fixture against the schema and every package against its interface. Dashboard is a static Vite/React site consuming `findings.json` + `experiments.json` only. Stats via numpy/scipy.

---

## 10. Execution model — waves & checkpoints (PRD §10–11)

**The rule that makes this work:** fixture-driven parallelism. Every downstream package develops against the 20 golden fixtures, never against another agent's live output.

**Ownership constraints (PRD §10.2):**
- Only the human + this Opus session edit `schema/` and `fixtures/golden/`.
- No agent edits another agent's package. Cross-package needs route through the human as an interface request.
- Every PR passes `make contract-test`. Every package ships passing unit tests. "Done" without a green suite is not done.
- No agent invents a rate, threshold, or constant. Constants live in config with a dated source.

**Waves:**

- **Wave 0 — Opus + human, sequential (un-skippable).** Write `packages/schema/`; hand-author the 20 golden fixtures; write `rates.yaml` (incl. OpenAI rows); stand up CI `contract-test`; **validate `audio.playback` capture on the Path-B local sink.** Nothing spawns until this is green and human-reviewed. *This is the highest-leverage block in the project.*
- **Wave 1 — parallel.** Opus: `agent/`+`otel/`, `verdict/`. Zen: `pricing/`, `detectors/{2,6,7,8,10}`, `dashboard/`. → **Checkpoint 1.**
- **Wave 2 — parallel.** Opus: `replay/` (hardest), `caller/`+corpus, `detectors/{1,3,4,5,9}`. → **Checkpoint 2.**
- **Wave 3.** Experiment matrix (6 variants × 250 traces) → `experiments/` stats → dashboard on real data → `METHOD.md` / `LIMITATIONS.md` / README with memorized numbers → 4-minute demo recording.

**Checkpoints, not continuous merge.** Between checkpoints, agents work; at checkpoints, the human reads. Cap at five parallel streams — review bandwidth is the real constraint (PRD §10.4).

**Agent brief template (PRD §10.5)** is used verbatim for every spawn: MISSION / PACKAGE / CONTRACT / INPUTS / OUTPUT / ACCEPTANCE / FORBIDDEN / WHEN-STUCK.

**Cut list, strictly in order (PRD §11):** dashboard polish → detectors 1/3/5 → open-loop replay → scenarios 4→2 → corpus 400→150. **Never cut pinned replay or verdict calibration.**

---

## 11. Wave 0 — Definition of Done

Wave 0 is complete, and Wave 1 may spawn, only when **all** of the following are true and human-reviewed:

1. `packages/schema/` defines every span type from PRD §3 with a validator; `make contract-test` runs.
2. 20 golden fixtures exist at `fixtures/golden/`, each schema-valid, each labeled with the detector it targets; the required distribution (§5.1) is met.
3. `pricing/rates.yaml` contains dated, sourced rates for the Path-B local providers (priced-as) **and** OpenAI (`gpt-5`, `gpt-5-mini`, `gpt-5-nano`).
4. CI runs `contract-test` green on all fixtures.
5. **`audio.playback` capture is validated** against the chosen local audio sink (the Detector-7 kill-check). If it cannot be captured, we stop and re-plan the audio layer before anything else.
6. This spec + the frozen schema are committed to git.

---

## 12. Risk register (PRD §12, updated for our stack)

| Risk | Severity | Mitigation |
|------|----------|------------|
| `audio.playback` not capturable | **Critical** (kills Detector 7) | Path B controls the audio sink directly; validated in Wave 0 DoD #5 before any dependent work. |
| Replay divergence too high | High | Pin tool responses by `args_hash`; report exclusion rate honestly; fall back to per-turn cost claims. |
| Verdict judge poorly calibrated | High | 60 hand labels first; κ<0.7 → deterministic tool-state only. |
| Cheap Zen agent drifts off-contract | Medium | Frozen contracts + fixtures + `contract-test` gate + strict brief; Zen output is trusted only because CI passes. |
| Synthetic traffic ≠ production traffic | Medium | State first and plainly. Claim = "this method finds and quantifies these waste classes," never "your fleet wastes X%." |
| Rate table stale/wrong | Medium | Dated sources in `rates.yaml`; know which rates were pulled and when. |
| WSL2 / native-Windows split causes friction | Low | Voice package in WSL2; analysis packages native. Documented in README. |

---

## 13. What this proves (PRD §13)

Turnstile on synthetic traffic does not prove any specific fleet wastes money. It proves the instrument can be built, that the waste classes are real and measurable, and that the author knows the difference between a measured claim and a suggestion. A CTO does not need a pre-audited fleet — he needs to believe it could be done.
