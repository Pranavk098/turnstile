# GLM overnight batch 2 — the last build batch (real numbers + demo surfaces + polish)

**Base:** `wave0-foundation @ 442f697` (676 pass / 2 skip, ruff clean). One `opencode/*`
branch per task (stacked series OK where noted). Claude reviews + merges each.

**Read this first.** The instrument is build-complete: Section A re-pricing remedies,
Section B verdict fixes, Section C cosine + labels registry, the barge-in headline +
lead_cap sweep all landed. **This batch adds NO new package.** Its value is (1) more
real, forwardable numbers from the barge-in harness we already built, and (2) putting
the barge-in headline in front of the viewer. After it, the next step is recording the
demo — not more building.

**Discipline (carried over, non-negotiable):** every modeled input is *stated* and
*swept*, never a single tuned figure; measure first, sample/vary second; label
conditional/modeled things verbatim. If a task needs a modeling decision you can't make
from the brief, **STOP and write a viability note** (like `viability-structured-divergence.md`)
— do not guess. No OpenAI spend anywhere in this batch (all local/deterministic).
Boundaries: `packages/agent`, `packages/experiments`, `packages/dashboard` only —
**never** `packages/schema` or `fixtures/golden`.

Priority order: Section 1 first (the real value), then Section 2, then Section 3 to fill
remaining time. Do them in order; each ends green + `ruff check packages/` clean.

---

## Section 1 — Real numbers from the barge-in harness

### T1 — tts_chunking measured: does finer TTS chunking lower the unheard-waste floor?
`tts_chunking` is the last RESERVED_VARIANT_FIELD (D6/D7's proposed remedy) with no
execution path. The lead_cap sweep already showed a **floor** at ~one synthesis chunk
(sentence-atomic). The remedy D6/D7 propose is finer chunking — so **measure it**:
- Add a chunk-**granularity** knob to the harness synthesis: `sentence` (today's default),
  `clause` (split on clause/comma boundaries), `word`. Each re-synthesizes through real
  Piper at that granularity (real audio + real chars per finer chunk — MEASURED, not
  modeled), lowering the atomic cancellation unit.
- Sweep granularity → barge-in waste at the fixed cited rate (0.15) and lead_cap (2.0s):
  `granularity → D7 $ · %TTS · [bootstrap CI]`. Expected monotone (finer → lower floor):
  "chunking at clause boundaries cuts the unheard-waste floor from ~4.2% to X%; word-level
  to Y%." That is a **measured remedy** for D6/D7 and a second demo number.
- Give `tts_chunking` a real execution path (harness-run, analogous to re-pricing's
  `run_repricing_matrix`): move it out of `RESERVED_VARIANT_FIELDS` and document the
  harness path in `variants.py`. Its saving is a **measured** harness result (not the
  conditional re-pricing bucket, not the gated backend bucket) — label it as such.
**Acceptance:** granularity sweep table (monotone at fixed rate+lead_cap), each point a
real Piper measurement with CI; `RESERVED_VARIANT_FIELDS == set()` (or documented why
tts_chunking now has a path); the anti-tuning invariants (measure schedule once, vary
granularity second) tested; honest label. Suite green.
**STOP-and-flag if:** clause/word re-synthesis materially changes Piper's audio in a way
that makes the char accounting ambiguous — write a note instead of forcing a number.

### T2 — latency–cost frontier (exploratory; viability note FIRST)
The trade every voice team makes blind: lower response latency costs model/TTS spend and
buys back telephony seconds. Turnstile prices both sides, so it can draw the curve.
**But the lever is a design choice — so this is a viability-note-first task, no build
until the note is reviewed.** In the note: identify the single cleanest latency lever the
corpus/harness *already prices both sides of* (candidates: model tier route→nano at the
measured ~2s vs ~9s; TTS buffer lead; reasoning effort), state what moves on each axis
(latency ↓, model/TTS $, telephony seconds), and propose the sweep. **STOP after the note.**
**Acceptance (note only):** a go/no-go with the chosen lever, both priced axes, and the
proposed sweep — `docs/superpowers/viability-latency-cost-frontier.md`. Zero code.

---

## Section 2 — Put the barge-in headline in front of the viewer

### T3 — Dashboard: barge-in headline panel
The dashboard (`packages/dashboard`) renders fixture-scale cost data but has **no
barge-in panel** — the demo headline is invisible in the UI. Add a panel that renders,
from `bargein_report.json` (the deterministic CLI output — regenerate/read it, don't
hardcode): the headline (**~4.2% of TTS spend billed-but-never-heard at 15% barge-in,
2s buffer**, with CI), the barge-in-rate sweep table (1.9%→7.9%), and the lead_cap sweep
table (4.2%→4.7%, with the **floor** annotation). Provenance string verbatim on the panel
(real Piper synthesis, modeled/swept barge-in rate + position). Match the existing
dashboard's honest two-tier labeling.
**Acceptance:** panel renders the real report numbers (hand-verified against the CLI),
provenance shown, no hardcoded magic numbers; a build_data/test asserting the panel data
traces to the report. Suite green.

### T4 — Dashboard: conditional-savings panel (Section A re-pricing)
Surface the Section-A re-pricing remedies (`run_repricing_matrix` output) in a **separate,
clearly-labeled** panel: `CONDITIONAL_SAVINGS_LABEL` verbatim ("deterministic conditional
saving — preservation unverified (Wave-2)"), never mixed with the gated 0.57% proven
number. One row per remedy (D2/D3/D4/D9/D10) with its deterministic Δ. This is the
"detected + quantified, not proven" tier made visible.
**Acceptance:** panel is visually + textually separated from proven savings; label verbatim;
numbers trace to `run_repricing_matrix`; test. Suite green.

---

## Section 3 — Honest polish (mechanical; fills remaining time)

### T5 — Manifest-vs-adjudication drift report (READ-ONLY; owner applies)
Produce a read-only report: for every golden fixture, `id → manifest expected_verdict →
current adjudicated label → match?`. Write it to `docs/superpowers/manifest-drift-report.md`.
**Do NOT edit `fixtures/golden/` or the manifest** — that's owner lane; this is the diff
the owner applies in one commit. Known drifters to expect: 06/07/08/10/11/13.
**Acceptance:** the report file, generated by a small committed script (so it's
reproducible); zero changes under `fixtures/golden/`.

### T6 — Test-gap fills (audit 07 §3, whatever remains)
Add the still-missing tests from the second audit's gap list — notably the
**divergence-mechanism test at the experiments layer** (a fake backend returning a
low-similarity pivot → trial `status="divergent"`, excluded from Δcost aggregates). Check
07 §3 for any others not yet covered and add them.
**Acceptance:** new tests, all green; each asserts a real behavior, not a tautology.

### T7 — Conditional bucket in the CLI output
Ensure `run_experiments.py` surfaces the conditional re-pricing bucket in its printed
summary + results JSON (labeled, separate from `recoverable_margin`), and a test asserts
it's present and distinct from proven savings.
**Acceptance:** CLI prints both buckets distinctly; results JSON carries both; test. Green.

---

## After this batch
Stop building. The remaining work is owner-lane: record the demo (barge-in headline +
the two war stories + the FDE close), apply the drift report, and the README voice pass.
Wave-3 (live conversational agent, structured-divergence with authored utterances, LLM
judge) stays entry-criteria'd, not started.
