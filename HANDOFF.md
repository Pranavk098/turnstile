# Turnstile — session handoff (continue here)

**For a fresh Claude Code session.** Read this, then read the ledger
`.superpowers/sdd/2026-08-30-turnstile-wave05-v1.1/progress.md` (the durable,
authoritative record of every task, ruling, and decision). Trust the ledger +
`git log` over any recollection.

**Date of handoff:** 2026-08-31 · **Branch:** `wave0-foundation` · **Tip:** `725b11c` · **~52 commits · workspace green (~520 tests)**

---

## 1. What Turnstile is (one paragraph)

A **margin profiler for voice AI agents.** It instruments a voice call
end-to-end (ASR→LLM→tools→TTS→telephony), prices every span from a config rate
table, detects **10 named waste classes**, adjudicates whether the call was
actually *resolved*, and **proves** each savings claim by counterfactually
replaying the call on a cheaper path. Target: an Observe.AI-style CTO. The
credibility hook is the owner's edge-inference-optimization background. Full
product spec: `turnstile-prd.md`. Build spec: `docs/superpowers/specs/`.

## 2. State — the full analysis instrument is BUILT and reviewed

```
Trace → pricing → verdict → detectors(×10) → replay → stats → dashboard
                                                   ↑ corpus + experiments feed it
```
Packages under `packages/` (all uv workspace members, root pyproject depends on all so `uv sync` installs them): `schema` (frozen contracts, v1.1), `pricing`, `verdict` (Resolution Ledger), `otel` (instrumentation shim), `detectors` (all 10 classes), `stats` (Wilson/bootstrap/aggregate), `dashboard` (static, renders REAL fixture-scale data), `replay` (credibility engine, injectable `DecisionBackend`), `corpus` (synthetic trace generator), `experiments` (baselines + 6-variant matrix + recoverable-margin + gated OpenAI backend + cost estimate + D7/D8 sweeps), `agent` (spike only — `playback_probe.py`, kill-check PASSED).

Everything was built **subagent-driven (SDD)**: fresh implementer per task → diff review (spec+quality) → fix loop → commit. Reviews caught real bugs. An external audit (`docs/audit/`, by "Antigravity/Opus 4.6") found 4 latent edge-case bugs — all verified + fixed (commit `b3ffd92`).

## 3. THREE lanes (this is how the spend limits are managed)

- **Claude (this session):** judgment-heavy builds, integration, all reviews, and everything that spends OpenAI credit or is demo-narrative. Budget note: the Claude monthly/5-hour limit repeatedly hit on **Opus** heavy builds → use **Sonnet** for implementers, **Opus/Sonnet** for load-bearing reviews, and delegate heavy builds out.
- **Zen (OpenCode, owner-driven):** cheap-model mechanical lane. Built `pricing`, `dashboard`, `stats` — verified against test oracles. Briefs in `docs/superpowers/briefs/zen-*.md`.
- **GLM 5.3 (OpenCode Go, owner-driven, NEW):** capable frontier model in its **own clone** `C:\Users\prana\turnstile-oc` (outside OneDrive — separate `.git`, share commits via fetch/remote), `opencode/*` branches off `wave0-foundation`. **Currently assigned: G1 recorder redesign** (brief: `docs/superpowers/briefs/glm-g1-recorder-redesign.md`). Its `opencode/lint-hygiene` (`d862f0e`) is a clean lint fix to pull in on next sync.

**Boundaries (PRD §10.2):** ONLY the owner + Claude edit `packages/schema/` and `fixtures/golden/`. Contract changes, demo narrative, and anything that spends OpenAI credit stay with owner/Claude.

## 4. IMMEDIATE next actions (in priority order)

1. **PAID matrix run — the owner's #1 priority, BLOCKED on the OpenAI key.** The owner greenlit it (~**$2.69**, not $150 — the estimate came back tiny). The gated OpenAI backend needs `OPENAI_API_KEY` set in the env (I do NOT handle the key value — the owner sets it via `setx OPENAI_API_KEY "..."`). Then run:
   `TURNSTILE_ALLOW_PAID=1  uv run python packages/experiments/run_experiments.py --paid --n 250 --seed 0`
   → produces the real **Tier-1 headline**: genuine `model_routing` (gpt-5→nano) outcome-preservation + Δcost + bootstrap CI. Then regenerate the dashboard data from it. **Ask the owner to set the key if not set.**
2. **D7/D8 sensitivity sweeps — DONE** (`packages/experiments/sweeps.py`, committed `83f3eea`, 524 tests green). Monotonic curves: D7 (barge-in rate) 5%→3.3% share … 30%→16.7%; D8 (silence-gap median) 100ms→77.7% … 200ms→81.9% (~82%) … 450ms→85.8%. Report: `.superpowers/.../sweeps-report.md`. Diff-review still pending (low-risk — results verified correct/monotonic). Use these in the demo to present D7/D8 magnitude as a function of an input.
3. **GLM is on G1** — when its `opencode/g1-*` branch is ready, review + merge. G1 promotes D8 from Tier-2 to Tier-1.
4. **Docs remaining:** `docs/METHOD.md`, `docs/LIMITATIONS.md`, `README.md` with the memorized numbers (PRD Appendix B). Draftable partly via Zen.
5. **Record the 4-minute demo** per `docs/DEMO.md`.

## 5. The honesty framing — MUST be preserved (owner cares deeply)

- **Two-tier claims** (`docs/DEMO.md`, `docs/CORPUS.md`): **Tier 1 = measured** (the replay experiment — real model calls, Δcost, outcome-preservation, bootstrap CI) = headline. **Tier 2 = instrumented, not measured** (voice-stack cost decomposition, D7 barge-in, D8 silence-tax on synthetic acoustics) = mechanism demonstrated, magnitude NOT claimed, presented as a *question* ("nobody measures this — do you know your number?"). **Tier 2 → Tier 1 with no code change once G1 lands** and the recorder emits real audio.
- **D8 is 82% of corpus findings** → present as a HYPOTHESIS + a sensitivity sweep, NOT a claim. Do **not** calibrate it down (that's picking the number you want).
- **D2/D6 don't fire on the corpus** → state as a *corpus coverage gap*, not an instrument failure. **Do NOT re-tune the generator to make them fire** — adjusting after seeing detector output is tuning-in-disguise (owner was emphatic).
- **Gates (`docs/GATES.md`):** G1 (recorder concurrency — GLM doing it — prerequisite for *trusting* D8) and G2 (`chars_synthesized` = generated/billed, never intended text — enforced in `otel.record_tts`; GLM must preserve it).
- **Generator constraints (`docs/CORPUS.md`):** sample from cited distributions (not hand-picked); never tune to detectors; params (barge-in rate, silence gap) reported as sensitivities.
- **Recoverable Margin % — corrected** (`turnstile-prd.md` §4.3 ERRATA): `Σ proven_savings / Σ total_cost × 100`, §8.3-gated (preservation ≥ 0.95 AND CI_lower(savings) > 0), reported as `[CI_lo, CI_hi]` + point estimate + the absolute $ (spend, savings, annualized). Never a bare point estimate.
- **The two verdict judgment lines** (the strongest thing in the repo — `docs/DEMO.md`): refusing to count a *rejected handoff* as an escalation; *declining to fabricate* a confident verdict on `unknown` (caps confidence at 0.6). Spoken lines, not footnotes.

## 6. Known deferred / Wave-2 (all documented in the ledger + `docs/audit/03-gap-analysis.md`)

LLM judge (verdict evidence source 5 — needs 60 hand labels + Cohen's κ ≥ 0.75); cosine-similarity half of D3 (only doc-id overlap done); `PARTIALLY_RESOLVED`/`MISROUTED` never emitted (needs scenario registry); D5 waste inclusive of reprompt turn; stale `d09` module docstring ("KNOWN WEAKNESS" now fixed); pricing post-condition uses bare `assert` (stripped under `-O`); corpus baselines are calibrated constants; live `agent/` (WSL2 Pipecat) blocked on G1.

## 7. How to continue (process)

Keep SDD discipline: dispatch a fresh subagent per task with a precise brief, generate a diff review package (`.claude/plugins/.../subagent-driven-development/scripts/review-package PLAN BASE HEAD`), review spec+quality, fix-loop, commit. Update the ledger every step — it is the recovery map. Subagents sometimes misreport git state ("not a git repo") — verify `git status` and commit recovered work. Never edit `schema/` or `fixtures/golden/` outside owner/Claude. Confirm before spending OpenAI credit.
