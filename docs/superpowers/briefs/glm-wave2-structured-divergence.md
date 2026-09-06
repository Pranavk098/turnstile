# GLM brief — Wave-2: structured-decision divergence (execution)

**Base:** `wave0-foundation` @ current tip. Branch `opencode/wave2-divergence`
(stacked series OK). Schema/fixtures/credit stay owner/Claude; Claude reviews +
merges. **Supersedes the sequencing** (not the goal) of
`docs/superpowers/briefs/wave2-structured-divergence.md` — its Item 1 is now
partly done free (vocab table below) and its "re-smoke n=30 before n=250" is
already measured: both nulled.

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

## Item 2 — per-kind decision-equality gate (only on Item-1 go)

Replace/augment `replay.py`'s difflib gate: parse original `decision_chosen`
AND replayed decision to labels per kind, compare labels. TDD against the
W3-C probes (authored preserve/break/divergent must still classify) plus new
kind-aware tests. Wire elicitation prompts into `OpenAIBackend`. Re-probe paid
(≤5 calls) then n=30 pilot before any n=250. Each step green + ruff clean.

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
