# Wave-2 Item 1 — structured-decision divergence viability check

**Author:** GLM 5.3 (OpenCode) · **Date:** 2026-09-01 · **Cost:** $0.00 (no API calls; local analysis of the deterministic corpus only)
**Brief:** `docs/superpowers/briefs/wave2-structured-divergence.md` Item 1. Per that brief: **no further work until the owner reviews this note.**

## Verdict: NO-GO on Item 2 as specified — for a reason the brief's checklist didn't anticipate

The label vocabulary **passes** (bounded, meaningful — §1). The elicitation
contract is definable and the parser is mechanically trivial (§2). But the
viability check surfaced a **blocker one layer below the labels**: the
corpus's decision *inputs* carry no signal. The caller side of every synthetic
turn is the placeholder `"Caller utterance for turn N."` — identical across
all six scenarios — so a real model reading the pinned context **cannot infer
the intended label**. Structured equality on this corpus would measure a
coin flip, not model fidelity. Any paid spend on Item 2 before a
corpus-authoring change would buy noise (§3).

**GO is cheap and concrete**: author per-scenario caller utterances (owner
lane), then run a *route-only* structured equality — which covers 100% of
what the routing-only paid variant actually acts on (§4).

## 1. Vocabulary per `decision_kind` (n=250, seed=0; deterministic, reproducible)

From `generate_corpus(250, 0)` (1,798 llm spans total):

| kind | spans | distinct labels | labels (count) |
|---|---:|---:|---|
| `route` | 231 | 6 | `refund` 51 · `cancel_subscription` 41 · `billing_dispute` 37 · `order_status` 37 · `tech_support` 33 · `appointment_reschedule` 32 |
| `slot_fill` | 404 | 1 | `request_slot` 404 |
| `tool_select` | 362 | 2 | `lookup_account` 191 · `retrieve_kb_article` 171 |
| `compose` | 617 | 3 | `inform` 453 · `complete_mutation` 113 · `close_call` 51 |
| `escalate_check` | 184 | 2 | `continue` 123 · `escalate` 61 |

Checklist results:

* **Bounded:** yes — 14 labels total across 5 kinds; every value is one of
  the generator's fixed constants (`generate.py:386–442`).
* **Meaningful:** partially, and kind-dependent:
  * `route` — the label IS the scenario intent (`decision_chosen =
    scenario.scenario_id`, candidates `[scenario_id, "other"]`), emitted at
    turn 0 where the caller speaks first. Semantically ideal for equality.
  * `escalate_check` — binary and meaningful: `escalate` only on terminal
    handoff turns; the scripted *early* escalation-predictable turn chooses
    `continue` (D9's narrative).
  * `tool_select` — bounded but **not context-determined**: the generator
    picks lookup vs retrieval by coin flip (`rng.random() <
    P_RETRIEVAL_GIVEN_TOOL_SELECT`, `generate.py:427`; P = 0.5 in
    `distributions.py`).
  * `slot_fill` — single label: equality is vacuous in both directions.
  * `compose` — `inform` is the mid-call filler; `complete_mutation` /
    `close_call` are terminal-structural (inferable from position + pinned
    tool effects).

## 2. Elicitation prompt contract + parser (designed, ready if/when unblocked)

Contract (appended to the existing CR-A render — pinned history, current
turn's caller ASR as the final user message — plus one system rule):

> `Respond with EXACTLY ONE of: {labels}. No other text, no punctuation,
> no explanation.`

where `{labels}` is the kind's allowed set from §1 (`route` also admits
`other`). Parser: strip whitespace/quotes, lowercase, exact-match against
the allowed set; one fallback pass on substring containment; otherwise
`PARSE_FAILURE` (a distinct outcome — never silently coerced to a label).

Mechanical parse reliability is estimated **high** (single-token constrained
output); confirming that needs the brief's ≤5-call owner-gated probe — worth
running **only after §3's blocker is fixed** (on placeholder prompts the probe
would measure parse mechanics on input we already know is signal-free).

## 3. The blocker: decision inputs are placeholders (`decision INPUT`, not labels)

* Every caller ASR transcript in the corpus is
  `TEXT_CALLER_UTTERANCE = "Caller utterance for turn {turn}."`
  (`generate.py:93`): **21 distinct ASR strings in 250 traces, all
  placeholders**, identical across scenarios. The TTS side is canned generic
  strings (`"Here is what I found for you."` etc.).
* Consequence for `route` (the kind that matters): the intended label is the
  scenario, but the utterance does not state it — "Caller utterance for turn
  0." looks identical in a refund call and a tech-support call. A real model
  picks uniformly among 6 labels ⇒ expected agreement ≈ 1/6. That is
  corpus noise wearing a measurement's clothes.
* `tool_select` is worse than uninferable — it is *rng-chosen by
  construction* (`generate.py:427`): comparing a model's tool choice against
  the corpus's coin flip measures the coin.
* This retro-explains smoke #3 exactly: the difflib ~0.04 divergence wasn't
  only "real text vs canned text" — there was **no signal in the input to
  agree on** in the first place.

## 4. The cheap path to GO (owner decision; no GLM lane change)

1. **Owner/Claude (corpus lane):** author per-scenario caller utterance
   pools — at minimum a distinct, intent-stating turn-0 utterance per
   scenario (6 strings to start); ideally turn-k continuation texts per
   outcome class later. Schema impact: none (transcripts are plain strings);
   `fixtures/golden/` untouched. This also upgrades CR-A's fix from
   "plumbing correct" to "input meaningful" and D8/D2's text-based math.
2. **Then Item 2 scoped minimal:** structured equality **on `route` only**
   (parse both sides to the 6+1 labels, compare) — the routing-only
   variant's pivot is the turn-0 `route` span, so this one kind carries the
   entire paid-run divergence signal. Other kinds keep the existing gate.
3. **Then** the ≤5-call probe (parse reliability on signal-bearing prompts),
   then the n=30 owner-gated re-smoke.

Item 3 (real baseline both sides) remains the follow-up after that, unchanged.

## 5. Suggested one-line addition for `docs/LIMITATIONS.md §1` (owner to fold)

> The synthetic corpus's caller-side transcripts are placeholders
> (`"Caller utterance for turn N."`), so decision labels are not inferable
> from pinned context even by a perfect model; any measured agreement on
> this corpus (text- or label-based) is noise until real utterances are
> authored (see `docs/superpowers/viability-structured-divergence.md` §3–4).

---

**Stopping here per the brief.** Deliverable complete: vocabulary
enumerated (§1), contract + parser defined (§2), reliability posture stated
with the probe deferred (§2), go/no-go delivered with a concrete unblock
path (§3–4). No replay/experiments code was changed; no spend incurred.
