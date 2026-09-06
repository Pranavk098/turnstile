# GLM brief — Wave-2: structured-decision divergence (execution)

**Base:** `wave0-foundation` @ `2d8bbb9` (Item 1 + recorder wiring merged +
consolidated 2026-09-06). Branch `opencode/wave2-item2-gate`. Schema/fixtures/credit
stay owner/Claude; Claude reviews + merges. **Supersedes the sequencing** (not the
goal) of `docs/superpowers/briefs/wave2-structured-divergence.md`.

**STATUS 2026-09-06:** Item 1 is DONE and merged — parser extended to route/compose,
elicitation contract wired (`ELICITED_KINDS`, slot_fill excluded), reasoning/truncation
capture landed, and the ≤5-call parse probe measured **4/4 in-vocab (≥4/5 bar cleared)**.
**Owner GO given for Item 2.** This brief is now an Item-2 build brief.

## Measured evidence (2026-09-06 paid runs, ~$0.45 total)

- Probe (W3-C harness + real backend, 3 calls): 3/3 divergent, sims 0.04–0.07.
- Pilot (`run_experiments.py --paid`, n=30/seed 8, 203 calls): 27/27 divergent,
  margin 0.00% [0.00, 0.00].
- Full matrix (n=250/seed 8, 1,734 calls): 217/217 divergent, margin 0.00%.
- Diagnostic (1 call): model reply was sensible (`gpt-5-nano`, 89 tokens —
  slot confirmation questions) but lexically disjoint from the baseline
  (refill-ready statement + closing) → difflib ~0.04. **Not an API failure:**
  the lexical gate itself is the blocker on open-ended decisions.

Conclusion: the difflib-on-full-text gate cannot survive contact with a real
model. Do not spend paid again until the gate compares decisions, not strings.

## Item 1 — viability close-out (mostly free; one ≤5-call gated probe)

Step 1 is DONE free (2026-09-06, corpus n=250/seed 8) — bounded vocabs everywhere:

| kind | decisions | labels |
|---|---|---|
| `escalate_check` | 185 | 2: continue / escalate |
| `tool_select` | 425 | 2: retrieve_kb_article / lookup_account |
| `slot_fill` | 443 | 1: request_slot |
| `route` | 217 | 6: billing_dispute / order_status / cancel_subscription / tech_support / appointment_reschedule / refund |
| `compose` | 600 | 3: inform / complete_mutation / close_call |

Remaining: (a) extend M-2 `parse_decision_chosen` to `route`/`compose`
(containment against the tables above; `escalate_check`/`tool_select` already
done); (b) define the per-kind elicitation prompt contract ("respond with
exactly one of {labels}" appended to the replay prompt); (c) ONE owner-gated
≤5-call probe measuring parse reliability (fraction of real completions that
parse to an in-vocab label per kind). **Go/no-go by owner on the note before
Item 2.** Crucial nuance: `slot_fill` is single-label, so label equality is
vacuous there — the gate must be kind-aware (`slot_fill` needs a
slot-value/content check, a narrower elicitation, or explicit exclusion with
its divergence reported, never folded).

## Item 2 — per-kind decision-equality gate (owner GO given; build this, TDD)

Replace `replay.py`'s full-text difflib divergence gate with a **kind-aware**
decision gate. This is the whole fix: the difflib-on-content proxy dies on real
replies (217/217 divergent null), so compare the *decision*, not the *string*.

### FINALIZED RULING — the gate is kind-dispatched (do NOT use one rule for all)
- **Bounded-vocab decision kinds — `route`, `tool_select`, `escalate_check`,
  `compose`:** divergent ⟺ parsed replayed label ≠ parsed original label. Parse both
  sides with the shared `parse_decision_chosen(kind, text, candidates)`. **An
  unparseable replayed reply (no in-vocab label contained) is divergent** — you cannot
  confirm the same decision, so never fold it as preserved; count + report it. This is
  the branch that turns the route-reroute matrix null into signal.
- **`slot_fill` — UNCHANGED path.** Single-label (`request_slot`) → label equality is
  vacuous, and its verdict rides on utterance *content* (clean-close), not the label.
  Keep the existing content/`_similarity` + re-adjudication behavior for slot_fill so
  the **W3-C authored probes classify EXACTLY as today** (preserve→preserved,
  break RESOLVED→ABANDONED→not-preserved and non-divergent, divergent→excluded). A
  label gate here would wrongly mark the break case preserved — that regression is the
  #1 thing your tests must forbid.
- Any other/unbounded kind: keep the difflib path (documented passthrough), never fold.

### Parser location (resolve cleanly; flag if awkward)
The gate lives in `replay.py`; `parse_decision_chosen` (+ its marker/vocab constants)
currently lives in `experiments/openai_backend.py`, and **experiments depends on replay,
not the reverse.** Relocate the *pure* parser into `turnstile_replay` (e.g.
`replay/decisions.py`) as the single source of decision parsing, and re-import it from
`openai_backend` for the backend's own use (no behavior change there — its tests stay
green). If the dependency direction makes this awkward, **STOP and flag** rather than
inverting deps or duplicating the parser.

### Tests (TDD, write first)
- W3-C regression: the three `fixtures/preservation/` probes classify identically to
  today under the new gate (preserve/break/divergent) — assert on `run_preservation`.
- Kind-aware gate units: for each bounded kind, same-label → not divergent; different
  label → divergent; unparseable replayed reply → divergent.
- Elicitation is already wired (Item 1b) — add a gate-level test that a same-decision
  paraphrase (different words, same label) is NOT divergent (the exact case difflib got
  wrong).

### Then, gated, in order (each its own owner yes for the paid steps)
1. Free full **mock** matrix regression: `run_experiments.py --n 250 --seed 0` still
   reproduces **0.57%** and `--seed 8` still **0.55%** (deterministic headline unmoved);
   mock preservation still structural. Non-negotiable pre-paid gate.
2. Owner-gated **≤5-call paid re-probe** — confirm a bounded-kind decision now compares
   by label (non-vacuous) before spend scales.
3. Owner-gated **n=30/seed 8 pilot**, then only on a clean pilot, **n=250/seed 8**.
   Compare paid against the **seed-8 mock (0.55%)**, not the 0.57% headline.
Each step green + `ruff check packages/` clean; offline/no-network preserved for all
non-paid paths. No `docs/METHOD.md` claim change until a measured number exists.

## Item 3 — truncation policy (folded in from paid-run findings)

Paid runs logged sporadic `completion reached max_tokens cap (256)` warnings
on nano AND mini. The capture fix (reasoning-token split + `finish_reason` in
the warning, `reasoning_tokens` returned on `ReplayedDecision`) lands in the
prep branch; this item decides policy from the next paid stderr: if the cap
eats reasoning, raise the cap or budget reasoning separately; if it eats
content, truncated trials must be flagged/excluded (a clipped reply is a
forced divergent trial), never silently scored.

## Item 4 — real-to-real baseline (deferred, owner/Claude lane)

Only if synthetic original labels prove too weak: generate corpus decisions
with a real model call too (~2× paid calls + corpus-generation change).
Never precedes Item 2.

## Acceptance

- Viability note with per-kind parse reliability + owner go/no-go on record.
- Gate compares labels per kind; W3-C probe cases still classify; suite green,
  ruff clean; offline/no-network preserved for all non-paid paths.
- No paid beyond the ≤5-call probe + n=30 pilot without a second gate.
- No `docs/METHOD.md` claim change until a measured number exists.
