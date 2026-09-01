# Turnstile — remaining work & next steps

**State snapshot:** `wave0-foundation @ c05f4b2` · **581 tests green** · `ruff check packages/` clean.
Built + reviewed + merged: full instrument (schema→pricing→verdict→detectors×10→replay→stats→dashboard),
hardened paid path (fail-loud variant guard, reproducibility manifest, trace-level resumable
checkpointing, timeout+retry, k=8 concurrency), corrected CR-A/CR-B, G1 recorder redesign (R12).
Deterministic Tier-1 headline computed (free): **recoverable margin 0.57% [0.49, 0.66]**, ~$126/yr @ 1M calls.
Honesty framing committed (METHOD.md, LIMITATIONS.md, DEMO.md).

**Lane rule (unchanged):** GLM owns implementation in its clone via `opencode/*` branches; Claude
reviews + merges. `packages/schema/` and `fixtures/golden/` are **owner/Claude ONLY** — GLM must not
touch them. Any OpenAI-credit spend is owner-gated (env `TURNSTILE_ALLOW_PAID=1` + `--yes` do NOT
authorize spend on their own). Each branch ends green with tests + `ruff check packages/` clean.

---

## Track 1 — Demo delivery (owner/Claude voice; NOT GLM)

The numbers + framing are already committed; this is narration + recording, kept in one voice.

| # | Task | Owner | Notes |
|---|---|---|---|
| 1.1 | `README.md` | owner/Claude | Narrate the committed numbers (METHOD/DEMO). Claude can draft; owner refines voice. |
| 1.2 | Dashboard vs corrected framing — **verify** the replay/margin panel reflects the deterministic 0.57% and the reframe, not stale "measured replay / MockBackend" language | Claude spec → GLM/Zen impl if changes needed | `packages/dashboard/`. Only a check + possibly relabel; flag if it overclaims. |
| 1.3 | Record the 4-min demo per DEMO.md | owner | No code gate remains before this. |

---

## Track 2 — Quick cleanups (one GLM branch + two owner-lane)

**GLM branch `opencode/cleanups` (small, one reviewable unit):**
- **B1** — CR-B companion label. `DELTA_COST_REAL_USAGE_LABEL` in `replay.py` says "includes render-scale
  mismatch"; imprecise (the companion is internally a clean arbitrage on real tokens; the scale gap is
  *between* the two figures). Reword to: priced on real replayed usage, smaller than the corpus's
  synthetic token counts; informational, not gated.
- **B3** — pricing post-condition uses a bare `assert` (`pricing.py`, stripped under `python -O`) →
  convert to an explicit `raise`.
- **B4** — stale `d09_escalation_debt.py` module docstring ("KNOWN WEAKNESS", fixed in 879babb) → update.
- Acceptance: suite green, ruff clean, no behavior change (B1/B4 are text; B3 keeps the same invariant).

**Owner/Claude-lane (GLM must NOT touch — `fixtures/golden/`):**
- **B2** — 11 pre-existing ruff findings (E741/F401) in `fixtures/golden/_author_rest.py` / `_builder.py`.

---

## Track 3 — Wave-2 product upgrades (GLM, sequenced; spend-gated)

These are the real credibility upgrades. Ordered by value/cost; each is its own brief + review cycle.

### 3A — Structured-decision divergence (makes the paid replay measure something real)
**Brief already written:** `docs/superpowers/briefs/wave2-structured-divergence.md`.
- **Item 1 (FREE viability check) — do FIRST, no spend.** Enumerate the corpus's `decision_chosen`
  vocabulary per `decision_kind`; define a decision-elicitation prompt contract + parser; estimate parse
  reliability (mock or ≤5 owner-gated calls). Deliver a go/no-go note. **Stop for owner review.**
- **Item 2 (build, if go):** replace `replay.py`'s difflib text gate with per-kind decision equality
  (parse original + replayed to labels, compare). Then an owner-gated n=30 re-smoke.
- **Item 3 (only after 2):** real baseline both sides (real call for the ORIGINAL decision too) — ~2×
  spend + a corpus-generation change (schema/corpus lane → owner/Claude co-owns).
- **Why:** today outcome-preservation is unmeasurable on the synthetic corpus (LIMITATIONS §1). This is
  the path to a defensible measured preservation number.

### 3B — Reserved-variant remedies (make D2/D3/D4/D6/D7/D9/D10 findings falsifiable)
Implement the replay transformations the `RESERVED_VARIANTS` encode so those findings' `proposed_variant`
becomes replay-executable instead of a fail-loud no-op: `context_strategy` (window/summarize),
`prefix_caching`, `retrieval_policy`, `tts_chunking`, `escalation_policy`, `tool_batching`. Each moves one
detector class from Tier-2 (detected+quantified) toward Tier-1 (replay-proven). Partially depends on 3A's
decision-parsing infra. **Needs a brief (Claude to write when prioritized).**

### 3C — Live agent integration (promotes D7/D8 to REAL audio → Tier-1)
Now unblocked by G1 (R12). Wire `packages/agent/` to a live voice stack (WSL2 Pipecat) recording through the
new `TraceRecorder`, emitting real audio-derived spans. Prerequisites: WSL2 Pipecat stack (owner), and the
G1 follow-up — **confirm single-task recording or add locking to `TraceRecorder`** (it is not thread-safe).
**Needs a brief + owner environment setup.** Biggest fidelity jump: D7/D8 magnitude becomes measured.

### 3D — Verdict/detector deferrals (smaller, independent)
- `PARTIALLY_RESOLVED` / `MISROUTED` never emitted → needs a scenario registry.
- LLM-judge evidence source (verdict source 5) — real no-op pending 60 hand labels + Cohen's κ ≥ 0.75.
- D3 covers only the doc-id-overlap half of redundant retrieval (cosine-similarity half deferred).

---

## Recommended immediate assignment for OpenCode

1. **`opencode/cleanups`** (Track 2: B1 + B3 + B4) — trivial, one branch, keeps momentum while the demo
   track proceeds in parallel.
2. **Track 3A, Item 1 — the FREE viability check** (brief exists). This is the highest-value next step and
   costs nothing; its go/no-go decides whether the paid replay can ever measure preservation. **Stop and
   report before Item 2** (Item 2's re-smoke is an owner-gated spend).

Everything else (3B, 3C, 3D) is sequenced after and gets its own brief when the owner prioritizes it.
Claude handles Track 1 (README draft, dashboard framing check) and B2 in parallel — no file overlap with GLM.
