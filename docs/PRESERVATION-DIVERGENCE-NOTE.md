# Preservation-under-divergence — Item 1 fork forensics (free; no paid runs)

**Status:** Item 1 complete → **STOPPED at the owner go/no-go** before any Item 2
oracle build. MODELED-tier analysis of the 17 real forks (paid n=250/seed 8,
`experiments/matrix-paid-n250-s8.json`); nothing here touches the measured 0.985
identity-preservation number, and **no fork was re-adjudicated** (the pinned-tool
trap was not approached: no `replay()` call, no rebuilt trace, no verdict run).

## 1. What is recoverable about the 17 forks, for free

The corpus is deterministic (`generate_corpus(250, 8)` reproduces every exemplar
trace), so each fork's **true intent, pivot kind, and original label** are known
exactly. The result JSON carries fork trace IDs only, and the checkpoint JSONL
persists `Trial` fields alone (`status` / `delta_cost` / `delta_latency_ms` /
`outcome_preserved`) — **the forked pivot's parsed label and utterance were never
persisted.** That is the load-bearing forensic finding: the forked side of all 17
forks is currently UNRECORDED data.

| trace_id | true intent (scenario_id) | registry requires | pivot kind | original label | forked label |
|---|---|---|---|---|---|
| corpus-8-00005 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00012 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00039 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00040 | order_status | none (lookup) | route | order_status | **UNRECORDED** |
| corpus-8-00052 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00058 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00065 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00112 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00124 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00126 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00132 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00177 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00206 | billing_dispute | adjust_billing (mutation) | route | billing_dispute | **UNRECORDED** |
| corpus-8-00220 | order_status | none (lookup) | route | order_status | **UNRECORDED** |
| corpus-8-00225 | cancel_subscription | cancel_subscription (mutation) | route | cancel_subscription | **UNRECORDED** |
| corpus-8-00230 | appointment_reschedule | reschedule_appointment (mutation) | route | appointment_reschedule | **UNRECORDED** |
| corpus-8-00234 | tech_support | none (lookup) | route | tech_support | **UNRECORDED** |

Verified properties (free, deterministic): every fork is a **turn-0 `route`
pivot** (the variant reroutes only `route`, and `_earliest_applicable_turn`
selects the first route span), the original label always equals the trace's
`scenario_id`, and every candidate set is the 2-way `[scenario_id, "other"]`.
Intent mass is concentrated: **13/17 cancel_subscription**, 2 order_status,
1 billing_dispute, 1 appointment_reschedule, 1 tech_support.

## 2. The classification space (what each possible forked label WOULD mean)

Per the brief's ruling, judged from `turnstile_verdict.registry` + existing
adjudicator semantics, deliberately ignoring pinned downstream tools:

| forked label class | registry-grounded classification | decidable? |
|---|---|---|
| another registered scenario B ≠ A | the agent understood the call as B; B's registry requirement is incompatible with A's true intent (different or absent required mutation) → **does not serve the intent: not preserved** | **YES** — pure function of (A, B) from the registry |
| `"other"` (in-vocab non-resolution) | no registry entry for `"other"`; "a route to `other` … judged per its registry rule" — the registry has no such rule | **NO → None** (a candidate rule "non-resolution → not preserved" exists but is NOT registry-justified today; needs owner ratification as a stated, sweepable rule) |
| raw passthrough (unparseable reply) | the gate already excluded it; "did the fork serve the intent" is not answerable from an unparseable value | **NO → None** |

`escalate_check` / `tool_select` / `compose` rules: none of the 17 real forks
exercise these kinds (all route), so their registry-grounding matters only for
the Item 2 oracle + authored fixtures. Flag now, before any build: the
brief's escalate sketch ("continue→escalate hands off, typically a resolution
via ESCALATED") leans on the adjudicator's committed-handoff rule, but under
"ignore pinned downstream" it assumes the forked path WOULD reach a committed
handoff — a modeling assumption, not a registry fact. It can be stated and
swept, but it is the weakest rule in the set and the owner should ratify it or
scope it out.

## 3. Decidable fraction — the honest bounds

Per-fork decidability depends on the unrecorded forked label, so the real-fork
decidable fraction is **bounded, not known: between 0/17 and 17/17.** Worst case
(all forks went to `"other"`/raw): zero decidable, no oracle value on real
forks, defer to open-loop. Best case (all cross-scenario): 17/17 decidable, all
not-preserved. The point estimate **cannot be computed without the labels** —
reporting a made-up fraction would be exactly the guessing this brief forbids.

## 4. Owner go/no-go — the decision put to you

- **Option A (recommended): GO on the Item 2 oracle build — free, TDD, no paid.**
  The rules above are crisp enough to implement as a pure, sweepable,
  docstring-stated function (`route` cross-scenario decidable; `"other"`/raw
  explicitly `None`; escalate/tool/compose rules authored per ratification).
  Authored fork fixtures in a NEW `fixtures/forks/` carry unambiguous
  ground-truth outcomes plus an explicitly-undecidable case. The re-analysis
  entry takes a forked-labels sidecar so the modeled figure computes the moment
  labels exist. The oracle future-proofs every later paid run regardless of
  what the 17 labels turn out to be.
- **Option B (paired, free, in-lane): persist forked pivot decisions** (parsed
  label + utterance) in the checkpoint/result from the next paid run onward, so
  forensics never again depends on reconstructing spend.
- **Option C (needs a separate owner yes — NOT taken): a ≤17-call paid pivot
  re-probe** to recover the 17 forked labels (nano, same prompts; ~$0.004). This
  brief says no paid runs, so it is only *named* here, with its exact shape, and
  not fired.
- If you judge the oracle not worth it without labels: say so and we defer the
  whole modeled figure to open-loop execution — that remains the honest ceiling
  either way.

**The measured 0.985 identity-preservation number is untouched by all of the
above and is never merged with any modeled figure.**
