# Brief — Live agent Phase 3: open-loop preservation-under-divergence (MEASURED)

**Base:** `wave0-foundation` @ `94251b5`. Branch `opencode/live-p3-openloop`. Reviewed +
merged by Claude. **Owner-gated paid, budget-capped. Build TDD.**

## Goal
The project's FIRST *measured* (not modeled) preservation-under-divergence number. Execute
the cheaper model's decisions **forward through the live loop to a terminal state**, then
adjudicate the real outcome — so we finally watch a verdict hold or fail when the cheaper
model decides *differently*. Per owner decision, report it under **TWO resolution rules,
side by side, never folded.**

## Use TEXT MODE, not voice
The measurement needs no audio (audio is the P2 demo). Extend the **text-mode** loop
(`turnstile_live` P1 / `run` path), not the voice loop — it's cheaper, faster, and lets the
cheaper model drive many turns. Reuse P2's `CappedLlmPolicy` for the decisions (paid gate +
free bucket).

## The mechanism (open-loop)
For a **budget-bounded** set of scenarios (start n≈20–30; the corpus scenarios or authored
probes), run each conversation **open-loop**: the capped cheaper model (`gpt-5-mini`/`nano`)
makes every decision across turns, the mock tools respond, until a terminal state. Compare
to the baseline path. A conversation is **divergent** when the cheaper model's decision
path differs from the baseline's. For each divergent conversation, decide whether it still
**resolved**, under both rules below.

## The two resolution rules (owner-decided: report BOTH, separately)
1. **Registry-grounded (the defensible figure):** the mock tools commit the terminal action
   per `turnstile_verdict.registry` (the scenario's required tool). A divergent path is
   preserved iff it reaches the registry-required resolution. Deterministic; reuses the
   fork-oracle's ground truth, now EXECUTED (the model can recover from a fork over several
   turns — the key gain over the static oracle). If the registry can't decide a scenario,
   that conversation is `None` (undecidable), listed, never guessed.
2. **LLM-judge (the lifelike companion):** a small-model (`gpt-5-mini`, free bucket) judge
   reads the final transcript and judges whether the caller's intent was resolved. Paid but
   cheap. Its bias is a stated caveat.

Report `preservation_under_divergence_measured` as **two figures**:
`{registry: X% (n_divergent=…), llm_judge: Y% (n_divergent=…)}` — each labeled, **never
folded into each other, never folded into** the measured identity-preservation (0.98) or the
modeled oracle (None). Also report `n_divergent`, `n_undecidable`, and the per-conversation
rows.

## Boundaries & discipline (hard)
- `packages/live/` (+ optionally a new `turnstile_experiments` entry for the runner) only.
  **NEVER touch** the `turnstile_agent` barge-in harness, `packages/schema`,
  `fixtures/golden`, `docs/METHOD.md`, `docs/LIMITATIONS.md`. Claude lands the number in
  METHOD.
- **Owner-gated paid, BUDGET-CAPPED: STOP and flag if estimated spend would exceed $2.**
  Stay in the free bucket via the cap. Report actual spend.
- **STOP and flag** if divergence is ~0 (nothing to measure), or if the registry can't
  decide most scenarios (report undecidable counts, don't force a number).
- The resolution rules + the open-loop harness are TDD'd with a mock/deterministic policy
  (free); the paid run only supplies the real cheaper-model decisions + the judge.
- Green + `ruff check packages/` clean.

## Acceptance
- Two separate **measured** figures (registry-grounded + LLM-judge) with `n_divergent`,
  kept apart from each other, from the 0.98 identity figure, and from the modeled-None.
- Open-loop harness + both rules unit-tested with a mock policy (free); the paid run
  reports the real numbers + actual spend (≤ $2).
- Undecidable conversations listed, never guessed. Divergence-is-zero handled honestly.
- `packages/live/` only; harness/schema/golden/METHOD untouched; suite green; ruff clean.
- Delivery report: both figures, n_divergent, spend, and 2–3 example divergent conversations
  (what the cheaper model did, and whether each rule called it resolved).
