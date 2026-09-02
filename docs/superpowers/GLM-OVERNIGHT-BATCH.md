# GLM overnight batch — remaining development, delegated

**Base:** `wave0-foundation` @ current tip. **One `opencode/*` branch per task**, off
`wave0-foundation`, shared back for Claude review + merge. Work top-down by priority;
whatever lands by morning gets reviewed.

**Hard rules (every task):**
- **Never touch `packages/schema/` or `fixtures/golden/`** — owner/Claude only. If a
  change *would* alter a golden fixture's expected value, STOP and flag it; add a new
  unit test instead.
- No OpenAI/credit spend. All work here is deterministic or local-model only.
- Each task ends green (`uv run pytest -q`) + `ruff check packages/` clean, with the
  tests named in its acceptance criteria.
- **Honesty rule (same as the corpus/barge-in work):** never present a modeled or
  conditional number as measured; label assumptions in the output/provenance; do not
  tune anything to a flattering figure.

**In progress (already handed off, not in this batch):** `opencode/leadcap-sweep`
(buffer-policy sweep for the barge-in number).

---

## Section A — Deterministic remedy re-pricing (highest value)

**Goal:** today only `model_routing` is replay-executable, so the recoverable-margin
headline is 0.57% (routing only). Implement the other remedies as **deterministic
re-pricing transformations** so each detector's `proposed_variant` produces a real,
gated savings contribution — turning "1 of 10 remedies proven" into a fuller,
still-honest recoverable-margin picture across the taxonomy.

**Approach (shared):** each remedy transforms the priced trace deterministically
(fewer tokens / cheaper rate / dropped spans), re-prices via `turnstile_pricing`, and
the Δcost is `transformed − original` — exactly the rate-arbitrage pattern
`model_routing` already uses (no backend calls). Add each as a new executable field in
`turnstile_experiments.guard.IMPLEMENTED_VARIANT_FIELDS` **only once its transform
exists**, and as a `VARIANTS` entry. **Do NOT change the existing `model_routing`
path or the 0.57% computation** — add alongside it.

**Honesty constraint (critical):** unlike `model_routing` (same workload, cheaper
rate — unconditional), these transforms *reduce or drop work*, so the saving is
**conditional on the change preserving the outcome**, which is unmeasurable on the
synthetic corpus (H-1). Label every such contribution **"deterministic conditional
saving — preservation unverified (Wave-2)"** in the result and margin output. Keep
them in a **separate bucket** from the unconditional `model_routing` saving so the
owner can present them distinctly. The owner decides in the morning whether/how to
surface them; your job is to build + label, not to headline.

**Per-remedy transforms** (do in this order; each its own branch or a stacked series):

1. **`prefix_caching=True` → D2.** Re-price the repeated system/history prefix tokens
   at the `cache_read` rate (already in `rates.yaml`) instead of full input rate. The
   prefix = tokens shared across turns (system + pinned history). Clearest win; pricing
   already supports cache rates.
2. **`tool_batching=True` → D10.** Collapse duplicate tool calls in a turn (same
   `args_hash`) to one billed call; Δcost = the deduped calls' cost. (D10 already
   detects the duplication — reuse its logic.)
3. **`context_strategy="window:8" / "window:N"` → D2/D4.** Truncate `context_tokens`
   (and the priced input) to the last N turns of history before each decision;
   re-price the reduced input. State N as the policy.
4. **`escalation_policy="threshold:0.85"` → D9.** Truncate the trace at the earliest
   predictable-escalation turn (verdict's `turn_of_no_return`, already computed);
   Δcost = the cost of the turns after it. This is the "predictable at turn 3, spent 9
   more" saving made concrete.
5. **`retrieval_policy="threshold:0.8"` → D3.** Drop retrieval spans / retrieved-token
   cost below the threshold; re-price. State the threshold model.
6. **`context_strategy="summarize:2000"` → D4.** Cap context to a stated token budget
   (model a summary as a fixed-size context); re-price. Fuzzier — state the assumption
   loudly; lowest priority in this section.

**Skip `tts_chunking` here** (D6/D7) — it interacts with the barge-in harness, not the
token/cost path; leave it to the acoustic track.

**Acceptance (per remedy):** a test hand-computing the Δcost from `rates.yaml` on a
small fixture-shaped trace; the remedy passes the §8.3 gate only when it should;
`recoverable_margin` reports it in the **conditional bucket** with the
preservation-unverified label; existing `model_routing` result unchanged. Suite green.

---

## Section B — Instrument correctness & calibration (safe, self-contained)

1. **Baselines calibration (GAP-07).** `baselines.json` p50/p75 are hardcoded
   constants, not real percentiles. Compute them as actual percentiles over the corpus
   (`compute_baselines` on `generate_corpus`), and write the computed values (with the
   n/seed used) rather than magic numbers. Detectors that read baselines (D4, etc.)
   must still pass. Acceptance: a test asserting the baseline percentiles equal the
   corpus's actual p50/p75 for the stated n/seed. Lane: `experiments` + `corpus` read.
2. **Verdict guard — non-clean end on informational (the sharpest confidently-wrong
   edge).** In `adjudicate.py`, an informational-intent trace currently defaults to
   `RESOLVED@0.70` even when `end_reason` is non-clean (`timeout`/`error`/
   `agent_hangup`). Add: non-clean `end_reason` on an informational path → NOT
   `RESOLVED` (cap confidence / mark unknown, matching the existing unknown-handling
   style). **Add a NEW unit test for this trace shape** — do not modify any golden
   fixture; if an existing fixture flips, STOP and flag it. Lane: `verdict`.
3. **Verdict — bind "asserts completion" to intent.** The FALSE_RESOLVE check uses an
   unbound substring match against final `output_text` (`adjudicate.py:~82`). Bind it
   to the scenario intent rather than a free substring. New unit test; same
   no-fixture-change rule. Lane: `verdict`.
4. **`decision_chosen` per-kind parsing (M-2).** `OpenAIBackend` sets
   `decision_chosen = raw completion text`. Parse it per `decision_kind`
   (`escalate_check` → escalate/continue containment; `tool_select` → tool name; else
   documented passthrough). Fake-client tests only; no spend. Lane: `experiments`.
   (Prereq for the Wave-2 structured-divergence work, so worth banking now.)

---

## Section C — Bigger deferrals (only if A + B are done)

1. **D3 cosine-similarity half (GAP-10).** D3 currently covers only doc-id overlap.
   Add the cosine-similarity half using a **local, offline** sentence-embedding model
   (e.g. a small `sentence-transformers` model pinned as an optional `--group`
   dependency, like the Piper extra) — no network at test time; tests skip cleanly
   without the extra. State the model + threshold. Lane: `detectors`.
2. **`PARTIALLY_RESOLVED` / `MISROUTED` emission (GAP-11).** These verdict labels are
   never emitted. Add a **minimal scenario registry** (scenario_id → required
   mutation/slots) and emit `PARTIALLY_RESOLVED` when some-but-not-all required
   effects occurred, `MISROUTED` when the handled intent ≠ the scenario intent. This
   likely changes some fixtures' expected verdict → **STOP and flag those to
   owner/Claude** (fixtures are our lane); land only the code + new unit tests, leave
   fixture updates to us. Lane: `verdict` (+ a new registry module).

---

## Not for tonight (blocked on owner input — listed so nothing is lost)

- **Structured-decision divergence** (Wave-2): blocked on **owner-authored per-scenario
  caller utterances** (`docs/superpowers/viability-structured-divergence.md`). GLM can't
  produce a meaningful preservation number until those exist. The `decision_chosen`
  parser (B4) is the only piece bankable now.
- **LLM judge (verdict source 5, GAP-09):** needs 60 owner hand-labels + Cohen's κ ≥
  0.75. Owner content first.
- **Full conversational live agent (GAP-02, Wave-3):** needs a real-time voice stack +
  environment; explicitly deferred — the native harness already produced the barge-in
  number without it.
- **`tts_chunking` remedy (D6/D7 acoustic):** belongs with the barge-in harness, not
  the deterministic cost path; scope later against the measured acoustic track.

---

## Review flow
Each `opencode/*` branch → Claude reviews (spec + correctness + honesty labels) →
merge to `wave0-foundation` → push. Owner reviews the batch's landed results in the
morning and decides presentation (especially Section A's conditional-savings bucket).
