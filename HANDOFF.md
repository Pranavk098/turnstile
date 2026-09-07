# Turnstile — session handoff (continue here)

**Keep this stamped.** At the end of a working session, update the line below with
the real tip SHA / commit count / test count / date, and delete any "next actions"
that are done. A stale handoff is the single biggest cause of re-derivation (audit
Task-1). Trust this + `git log` + `docs/DECISIONS.md` over any recollection.

**Stamp:** 2026-09-07 · branch `wave0-foundation` · tip `e62487c` · 162 commits ·
**859 passed / 4 skipped**, `ruff check packages/` clean. Publish-polish (README + hero +
`make demo` + dashboard guided-tour), D-lite (fork-persistence + truncation), and the
Task-2 **arch-migration** (`stats`→replay, `otel`→agent, conftest cleanup) all merged —
audit Task-2 target layout reached, zero-drift verified. **`uv sync` after pulling** (the
package layout changed). All three delegated lanes done; remaining roadmap is B (real
data) + C (live agent), both owner/Claude-scoped. **Wave-2 Item 2 MERGED**
(kind-aware divergence gate): `replay.py` now dispatches — bounded kinds
(`route`/`tool_select`/`escalate_check`/`compose`, `decisions.BOUNDED_LABEL_KINDS`)
diverge iff the replayed parsed label ≠ original label (unparseable = divergent, never
folded); `slot_fill` keeps the content/`_similarity` path (W3-C probes classify
identically — break stays not-preserved & non-divergent, re-verified). `parse_decision_chosen`
relocated to `turnstile_replay/decisions.py` (single source; `openai_backend` re-imports).
Free mock regression reproduces the pinned headline (seed 0 = 0.57%, seed 8 = 0.55%,
0 divergent). Wave-2 Item 1 + recorder wiring also consolidated. **PAID RUN DONE +
MEASURED (owner-gated, ~$1.28 total to date):** re-probe → pilot → n=250/seed 8 (1,734
calls, ~$0.39) all landed. The label gate turned the flat 0.00% lexical null into real
signal: **routing forks at 7.8%** (17/217, real different routes), **verdict preservation
= 0.985** (197/200 non-divergent pivots — the project's FIRST measured, non-structural
preservation number: 3 content-driven flips under identical routing), **margin 0.573%
[0.481, 0.667]** (paid n=250/seed 8; compare to seed-8 mock 0.55%, NOT the seed-0 0.57%
headline — the ~0.57% rounding match is coincidental, different populations). `docs/METHOD.md`
+ `docs/DECISIONS.md` updated (preservation reclassified Measured→**Partially-measured**);
paid result JSONs are gitignored (live in the OpenCode clone). **Preservation-under-
divergence — the modeled BRIDGE is built (Item 2, merged):** `turnstile_verdict.fork_oracle`
judges a fork against ground-truth intent via the registry (never re-adjudicates through
pinned tools), reported as a SEPARATE modeled figure (`preservation_under_divergence_modeled`,
Instrumented tier, never folded into the measured 0.985). Re-analysis entry:
`python -m turnstile_experiments.preservation_divergence --result <paid json> [--sidecar labels.json]`.
**BUT no number yet — data gap:** the paid matrix did NOT persist forked labels, so the
real 17 forks are all `unrecorded` → `modeled=None` (None by data, not modeling weakness).
To get a modeled number: capture forked labels — either a ≤17-call owner-gated recovery run
producing a `--sidecar labels.json`, or a future fork-persisting matrix run. **OPEN (real
measured ceiling):** preservation under divergence *measured* (not modeled) still needs
open-loop execution of the divergent path (the deferred live agent). Item 3 truncation
policy (2/1,734, non-distorting) noted. Only doc-only `opencode/perf-audit` remains stray.
Wave-3 core COMPLETE:
W3-A ingest + W3-B explorable UI + W3 Item 5 (ingest report wired into the dashboard
with honest D6/D7/D8 absence) merged; all three recoverable-margin gates converged on
the canonical `ci_upper < 0`. W3-C preservation-measurement **scaffolding** merged
(`fixtures/preservation/` + `experiments/preservation.py`): the deterministic harness
proves outcome-preservation is now a real function of the replayed decision
(preservation_rate 0.5, divergence 0.33 on authored non-pinned probes) — the one
remaining step to a *measured* number is the owner-gated paid run (see §4).

---

## 1. What Turnstile is
A **margin profiler for voice-AI agents.** It instruments a call end-to-end
(ASR→LLM→tools→TTS→telephony), prices every span from a dated rate table, adjudicates
whether the call was actually *resolved*, detects 10 named waste classes, and — for
the one remedy it can execute — *proves* the saving by counterfactually replaying the
call on a cheaper path. Target: an Observe.AI-style CTO; the credibility hook is the
owner's edge-inference background. Product spec: `turnstile-prd.md`.

## 2. State — Waves 0, 1, and 2 are COMPLETE
The full instrument is built, reviewed, hardened, and honestly framed:
`schema (v1.1) → pricing → verdict → detectors(×10) → replay → dashboard`,
plus `corpus` (synthetic generator), `agent` (**NOT a spike — the load-bearing
barge-in harness that produced the Tier-1 D7 number**, and now home to the G1
overlap-capable recorder), and `experiments` (matrix + re-pricing remedies + backends
+ sweeps + bargein report). **Package layout (post arch-migration `e62487c`):** `stats`
folded into `turnstile_replay.stats`, the `otel` recorder into `turnstile_agent`; those
two packages no longer exist. The dashboard is a self-contained editorial report (embedded fonts,
SVG charts); a `home.html` landing page landed as a frozen Wave-1 design baseline
(a35347c), to be **extended not replaced**.

**The numbers we stand behind:** measured barge-in waste ~4% of TTS spend (real
Piper; finer chunking recovers it to 2.3%/1.2%); deterministic recoverable margin
0.57% [0.49, 0.66]. Outcome-preservation is NOT measured (synthetic corpus can't —
see `docs/LIMITATIONS.md`). No paid n=250 run was ever needed; it would re-measure a
pinned quantity.

## 3. Boundaries, decisions, delegation → `docs/DECISIONS.md`
Read it. Lane boundaries (schema/fixtures owner+Claude only; credit/narrative =
owner/Claude), the delegation model (GLM implements in its clone, Claude reviews +
merges), the honesty tiers, the variant-execution model, and the "where truth lives"
map all live there — version-controlled, so they reach GLM's clone (the local ledger
does not).

## 4. IMMEDIATE next actions — Wave 3 (owner-chosen 2026-09)
Goal reframed: **no demo video** — build the product into a live CTO walkthrough.
- **W3-A — real-data ingestion** (`turnstile_ingest`) — **DONE** (merged): real
  call-log → v1.1 `Trace`; the FDE "point it at your calls" motion. 7-call sample.
- **W3-B — explorable product UI** — **DONE** (merged): `build_data.py` decoupled
  from `index.html`; landing page + navigable dashboard (call list → per-call drill).
- **W3 Item 5 — wire ingest into the dashboard** — **DONE** (merged `e62ac76`): the
  ingest report renders end-to-end via `sample/manifest.json` + a golden/ingest source
  switch; D6/D7/D8 shown ABSENT ("no data for this input") never zeroed; margins
  dataset-stamped (2.69% · 7 ingest calls); ingest `_recoverable_margin` converged onto
  the canonical §8.3 gate (`ci_upper < 0`). Verified: render (DOM: 3 absent rows), tests
  (`test_ingest_wire.py`), 770/4, ruff clean.
- **Task-2 gate residue — DONE:** all three recoverable-margin gates (margin.py,
  build_fleet, ingest) converged on canonical `ci_upper < 0`.
- **W3-C — preservation measurement — DONE + MEASURED:** the paid runs happened
  (re-probe → n=30 pilot → n=250/seed 8, ~$1.28 total). The kind-aware divergence gate
  turned the old lexical null into signal: **7.8% fork rate, 0.985 verdict preservation**
  on agreement, **margin 0.573%**. `docs/METHOD.md`/`DECISIONS.md` updated (preservation
  → Partially-measured). Preservation-**under-divergence**: the `turnstile_verdict.fork_oracle`
  bridge is built (modeled tier, never folded into 0.985) but returns None on this corpus
  (route forks are all `"other"` → registry-undecidable). Real measured number needs
  open-loop execution (live agent) OR corpus enrichment (richer route candidates).
- **Deferred:** live conversational agent (Pipecat/WSL2) — the C lane, and the open-loop
  ceiling for preservation-under-divergence.

### Delegation queue (2026-09-07)
Owner-chosen roadmap: **A (publish polish) → D-lite → B (real data) → C (live agent, last).**
- **A — publish polish — DONE:** README rewrite + hero + `make demo` (mine), and the
  dashboard guided-tour legibility polish (merged `11c791c`).
- **D-lite — DONE:** fork-persistence + truncation flag-and-exclude (merged `29d501d`):
  divergent trials self-document `forked_label`/`forked_text`/`finish_reason` (analyze_forks
  needs no sidecar); `finish_reason=="length"` → `status="excluded"` + `n_truncated`/
  `truncated_exemplars`, cap not raised. Mock regression unmoved (0.57%/0.55%, 0/0).
- **Architecture migration (Task-2 B/C/G) — DONE** (merged `e62487c`): `stats`→
  `turnstile_replay.stats`, `otel` recorder→`turnstile_agent`, all 10 dead conftest
  sys.path shims removed, `uv.lock`/root pyproject pruned. Verified zero-drift: 859
  passed, ruff clean, mock margins byte-identical (0.5731…/0.5471…), recorder.py a 100%
  verbatim move (OTel emission identity kept). **After pulling, run `uv sync`** — the
  package layout changed. This completes the audit Task-2 target layout.
- **NEXT — B (real-data) and C (live agent) are NOT clean parallel delegations yet** — B touches
  fixtures/corpus (owner/Claude) + moves measured numbers; C needs its own design/spike.
  Owner/Claude-driven until scoped.
- **Delegation hygiene:** the executor must push EACH task as its own `opencode/*` branch
  (the exp-hardening work arrived as loose working-tree edits, not a branch — reviewable
  only because it was disjoint from the dashboard edits).
- **Process (audit Task-1):** trivial changes (<~50 lines, no schema/contract) skip
  the brief/report ceremony — just a clean commit; no empty-message merge commits;
  keep this HANDOFF + `docs/DECISIONS.md` current.

### Wave-3 architecture target (audit Task-2 — migrate ONCE, into this shape)
The simplification audit's value is a target layout; do the structural moves *as part
of* Wave-3 (which already adds a package + reshapes toward a product), not as separate
pre-emptive churn. Target: `schema` (frozen) · `engine` (pricing+verdict+replay+stats)
· `corpus` · `experiments` · `acoustic` (detectors+agent+recorder) · new `ingest` ·
CLIs. Do during the Wave-3 migration:
- **B/C — package merges:** `stats` → `replay` (import rename in 3 files); `otel`
  recorder → `agent` (merge only — do NOT drop the OTel SDK emission or change the
  post-G1 timing model; both are load-bearing). Cosmetic value, workspace-wide churn —
  hence bundled into the one migration.
- **G — conftest sys.path shims:** the root dev group installs every member editable,
  so the `verdict/pricing/corpus/detectors/conftest.py` `sys.path` inserts may be dead;
  verify by removing one + `uv run pytest packages/verdict -q`, remove all if green.
- **A — DONE** (this session): `experiments/__init__.py` lazily loads the acoustic
  extras so the headline path imports without the spike stack.
- Skipped as not-worth-it: E (`run_matrix`/empty `RESERVED_VARIANTS` — honest doc
  artifacts) and F (CLI consolidation — cosmetic).

## 5. How to continue
GLM gets acceptance-criteria'd briefs in `docs/superpowers/briefs/`, builds overnight
on `opencode/*`, Claude reviews + merges. Never edit `schema/` or `fixtures/golden/`
outside owner/Claude. Confirm before spending OpenAI credit (none is needed for
Wave 3). Verify `git status`/`git log` — subagents/clones sometimes misreport state.
