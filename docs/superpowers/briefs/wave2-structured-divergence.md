# Wave-2 brief — measured outcome-preservation (structured-decision divergence)

**Status:** queued, not started. Owner-sequenced after smoke #3 established that
the paid replay on a synthetic corpus cannot *measure* outcome-preservation
(divergence gate vacuous vs canned text; verdict-preservation structural, H-1).
See `docs/METHOD.md` + `docs/LIMITATIONS.md §1`.

Goal: give the replay experiment a preservation/agreement signal that is
**non-vacuous and non-structural**, so a bounded paid run can measure something
real — replacing the text-similarity divergence gate with a per-decision-kind
**decision equality** check.

## Item 1 — FREE viability check (do this first; no spend)

The whole approach is only worth building if the corpus's decision labels are a
real, parseable decision vocabulary. Verify, at zero cost:

1. Enumerate the distinct `decision_chosen` values the corpus actually emits per
   `decision_kind` (e.g. `route` → `handle_billing`/`escalate`/…; `escalate_check`
   → escalate/continue; `tool_select` → tool names). Confirm they are a bounded,
   meaningful vocabulary, not filler.
2. Define a **decision-elicitation prompt contract**: a system/user prompt that
   makes a real model emit one of that kind's allowed labels (e.g. "Respond with
   exactly one of: {labels}"), and a parser from completion → label.
3. On a tiny FREE probe (mock or ≤5 real calls, owner-gated), estimate how
   reliably a real model's output parses to a label in-vocabulary. If parse
   reliability is poor, structured divergence is not viable — stop and report.

Deliverable: a short viability note (labels per kind, the prompt contract, parse
reliability estimate, go/no-go). **No further work until owner reviews it.**

## Item 2 — Structured-decision divergence (only if item 1 is go)

Replace `replay.py`'s `difflib` text-similarity gate with per-kind decision
equality: parse both the original `decision_chosen` and the replayed decision to
labels, and compare labels. `outcome_preserved`/divergence then measure "did the
cheaper model make the same DECISION as intended" — the real question. This is
the `tool_select`-sensitivity / M-2-parsing upgrade already flagged as a Wave-2
entry-criterion. Add the elicitation prompt to `OpenAIBackend`, parse
`decision_chosen` per kind (M-2), and re-smoke (n=30, owner-gated) before any
n=250.

## Item 3 — Real baseline, both sides (only after item 2)

If a synthetic *original* label is too weak a baseline, generate the corpus's
original decision with a real model call too, so divergence compares real-to-real.
~2× paid calls + a corpus-generation change (schema/corpus lane = owner/Claude).
Follows item 2 — never precedes it (don't pay double to compare against labels
nobody defined).

## Boundaries
Same as `glm-paidrun-hardening.md`: GLM owns replay+experiments; schema/fixtures
and any credit spend stay owner/Claude; Claude reviews + merges; each item ends
green with tests.
