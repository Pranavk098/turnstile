# Brief — Wave-3 W3-C: deterministic preservation-measurement scaffolding

**Base:** `wave0-foundation` @ `23bd73b`. Branch `opencode/w3c-preservation-harness`.
Reviewed + merged by Claude. **Build this TDD.**

## What this is (and is NOT)
Outcome-preservation is the one number Turnstile honestly labels **not measured**
(`docs/METHOD.md`). It is unmeasurable on the current corpus for two reasons, and
**both are INPUT problems, not missing machinery** — the replay engine already
computes divergence and preservation:
- **Vacuous divergence:** the corpus's baseline `output_text` is a canned placeholder
  (`"Let me look into that for you."`), so any real reply scores ~0.04 similarity and
  is marked `divergent` → excluded → preservation never computed.
- **Structural preservation:** golden verdicts ride on *pinned tool effects*, so
  re-adjudicating a replayed decision yields the same label regardless of the decision
  → preservation ≈ 1.0 by construction.

This brief builds the **deterministic scaffolding** that removes both, so preservation
becomes a real function of the decision — driven by an **authored** `DecisionBackend`
(no model call, no network, no credit). The real OpenAI backend later drops into the
**same** injection slot to produce the actual measured number — that paid run is a
SEPARATE, owner-gated step and is **explicitly OUT of scope here**.

**This pass does NOT:** make any real model call; claim any measured preservation
*number*; change any claim in `docs/METHOD.md` / `docs/LIMITATIONS.md`. The honest
artifact is "mechanism validated + non-vacuous on authored cases; the number awaits the
gated paid run." (Claude will land the METHOD update with that run.)

## Boundaries & discipline (hard)
- **NEVER touch `packages/schema/` or `fixtures/golden/`.** The probe fixtures live in a
  NEW dir `fixtures/preservation/` so the dashboard's pinned 23-fixture fleet is
  untouched. No schema changes; no adjudicator (`packages/verdict/`) changes; no replay
  logic (`packages/replay/`) changes — you FEED these existing components, you do not
  edit them. If a case seems to require editing the adjudicator or replay, **STOP and
  flag** — do not fake a flip.
- No hardcoded outcomes: the harness runs the real `adjudicate()` + real replay path.
- Green + `ruff check packages/` clean; fully static/offline/no-network.

## The mechanism you are exercising (read these first)
- **Adjudicator content path** `packages/verdict/src/turnstile_verdict/adjudicate.py`,
  `_adjudicate_informational()` (~line 440): for a trace with **no required
  mutation/handoff**, the verdict rests on utterance content. Specifically, with
  `end_reason = caller_hangup` and a final `llm.decide` whose `decision_kind = slot_fill`:
  - final utterance CONTAINS a `CLOSING_KEYWORDS` (line 124) hit within the last
    `CONFIRMATION_WINDOW_TURNS = 2` turns → `_has_clean_close` True → **RESOLVED**
    (`CONF_RESOLVED_INFORMATIONAL = 0.70`).
  - final utterance has NO closing keyword → soliciting slot_fill + caller_hangup →
    **ABANDONED**.
  `_has_clean_close()` (line 229) scans `llm.output_text` of the tail turns — so a
  REPLAYED decision that changes the final utterance flips the verdict via text alone.
- **Replay divergence + preservation** `packages/replay/src/turnstile_replay/replay.py`:
  `_similarity()` = `difflib.SequenceMatcher.ratio()` on `output_text`;
  `DIVERGENCE_SIMILARITY_THRESHOLD = 0.75` (line 71). If the replayed pivot decision is
  `< 0.75` similar to baseline it is marked `status="divergent"` and
  `outcome_preserved=None` (EXCLUDED — preservation not computed). Otherwise it is
  re-adjudicated and `outcome_preserved = (new_verdict.label == original_verdict.label)`
  (~line 245).
- **Backend injection** `packages/replay/src/turnstile_replay/backend.py`:
  `DecisionBackend` protocol `(ReplayContext, LlmDecide, VariantSpec) -> ReplayedDecision`;
  `MockBackend` (line 145, identity-replays); `set_backend()` / `reset_backend()`
  (`_DEFAULT_BACKEND` line 180). Inject your authored backend via `set_backend`; always
  `reset_backend()` in a fixture teardown so global state never leaks between tests.
- **Fixture shape reference:** `fixtures/golden/00_baseline_clean.json` (a v1.1 `Trace`).

## THE CRUX (target this deliberately, do not discover it by surprise)
Preservation is only computed on trials that are **NOT divergent** (≥ 0.75 similar). So
the verdict-FLIPPING variant must live in the band **"similar enough to be
re-adjudicated (≥ 0.75) yet different enough to flip the verdict."** Achieve it by
authoring a baseline final utterance long enough that DROPPING the short closing phrase
(e.g. `"you're all set — anything else?"`) still leaves ratio ≥ 0.75 against baseline,
while `_has_clean_close` now returns False. If you cannot construct a case that is
simultaneously non-divergent AND verdict-flipping, **STOP and flag** — that is a real
finding, not something to force.

## Deliverables
### 1. Probe fixtures — `fixtures/preservation/*.json`
A minimal set (~2–3 v1.1 `Trace` files) of **informational intent / no required
mutation** conversations, `end_reason = caller_hangup`, final `llm.decide`
`decision_kind = slot_fill`, with **real, non-canned** baseline `output_text`. At least
one baseline must adjudicate to **RESOLVED** via a clean-close keyword. Author them so
the pivot the replay engine selects IS the verdict-load-bearing final utterance (verify
in a test; if replay's pivot selection does not target it, STOP and flag).

### 2. Authored variant backend + harness — `packages/experiments/.../preservation.py`
- An authored `DecisionBackend` that, per probe, returns a chosen cheaper-path
  `ReplayedDecision` (`output_text` + parsed decision). Provide the three contrasting
  variant decisions below.
- `run_preservation(backend=None) -> report` that loads `fixtures/preservation/`, runs
  the real replay path through the injected backend, and aggregates `preservation_rate`,
  `divergence_rate`, and per-probe rows (`status`, `original_label`, `new_label`,
  `similarity`, `outcome_preserved`). Default backend = the authored one; the real
  OpenAI backend is a drop-in for the same slot (leave a one-line, clearly-labeled swap
  point; do NOT wire or call it).
- A module docstring stating the honesty framing above (mechanism, not a measured
  number).

### 3. Tests (TDD — write first) — `packages/experiments/tests/test_preservation.py`
Assert the mechanism is now **non-trivial and decision-sensitive**:
- **Preserve case:** a benign paraphrase that keeps a closing keyword, ≥ 0.75 similar →
  `status != "divergent"`, verdict unchanged, `outcome_preserved is True`.
- **Break case (the money case):** a variant that drops the closing keyword while
  staying ≥ 0.75 similar → `status != "divergent"`, verdict flips RESOLVED→ABANDONED,
  `outcome_preserved is False`.
- **Divergent case:** a variant < 0.75 similar → `status == "divergent"`,
  `outcome_preserved is None` (excluded, NOT counted as preserved).
- Aggregate: over the probe set, `preservation_rate` is strictly between 0 and 1 (proves
  it is a real function of the decision, not structurally 1.0), and `divergence_rate` is
  not 100% (proves divergence is non-vacuous on real baseline text).
- Backend hygiene: `reset_backend()` in teardown; a test confirms global backend state
  does not leak.

## Acceptance
- `fixtures/preservation/` holds valid v1.1 traces; `fixtures/golden/` and
  `packages/schema/` diffs are EMPTY; `packages/verdict/` and `packages/replay/` diffs
  are EMPTY (feed, don't edit).
- The three cases above pass; `preservation_rate ∈ (0, 1)`; `divergence_rate < 1.0`.
- No network / no model call / no `docs/METHOD.md` claim change.
- Suite green, `ruff check packages/` clean.
- In the delivery report: the exact `preservation_rate` / `divergence_rate` on the probe
  set, the similarity ratios of the preserve/break/divergent variants (show the break
  case really is ≥ 0.75), and any STOP-and-flag notes.
