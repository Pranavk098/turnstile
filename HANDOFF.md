# Turnstile — session handoff (continue here)

**Keep this stamped.** At the end of a working session, update the line below with
the real tip SHA / commit count / test count / date, and delete any "next actions"
that are done. A stale handoff is the single biggest cause of re-derivation (audit
Task-1). Trust this + `git log` + `docs/DECISIONS.md` over any recollection.

**Stamp:** 2026-09-06 · branch `wave0-foundation` · tip `e62ac76` · 136 commits ·
**770 passed / 4 skipped**, `ruff check packages/` clean. Wave-3 core COMPLETE:
W3-A ingest + W3-B explorable UI + W3 Item 5 (ingest report wired into the dashboard
with honest D6/D7/D8 absence) all merged. Product ingests real-format call logs and
renders them honestly, end to end.

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
`schema (v1.1) → pricing → verdict → detectors(×10) → replay → stats → dashboard`,
plus `corpus` (synthetic generator), `otel` (G1 overlap-capable recorder), `agent`
(**NOT a spike — the load-bearing barge-in harness that produced the Tier-1 D7
number**), and `experiments` (matrix + re-pricing remedies + backends + sweeps +
bargein report). The dashboard is a self-contained editorial report (embedded fonts,
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
- **OPEN (Task-2 residue):** `build_data.build_fleet`'s margin still uses the looser
  both-CI-same-sign gate — the 2nd of the 3 divergent gate copies (ingest is now the
  canonical one). Agrees with canonical on current data; converge it when next in that file.
- **Deferred:** live conversational agent (Pipecat/WSL2); measurement completion
  (W3-C: authored utterances → structured divergence → real preservation number).
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
