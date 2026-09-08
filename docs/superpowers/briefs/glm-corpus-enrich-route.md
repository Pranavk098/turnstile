# Brief — corpus route-candidate enrichment (unblock the fork oracle)

**Base:** `wave0-foundation` @ `26fda29`. Branch `opencode/corpus-enrich-route`.
Reviewed + merged by Claude. **Build TDD. No paid runs.**

## Why
The fork oracle (`turnstile_verdict.fork_oracle`) returns `None` on the current corpus:
route decisions offer only the 2-way candidate set `[scenario_id, "other"]`, so a fork
can only be `"other"` (registry-undecidable). Widen the route choice to the real
scenarios so a fork can land on another **registered** scenario the oracle can decide —
and, as a bonus, retire the "2-way choice inflates agreement" caveat in METHOD.

## THE LOAD-BEARING CONSTRAINT (read twice)
This change must be **RNG-neutral**. The deterministic headline (0.57% seed 0, 0.55%
seed 8) is computed over the seeded corpus; if your edit consumes even one `rng` draw in
the generation path, the entire RNG stream shifts and the headline moves. The route
candidate list at `packages/corpus/src/turnstile_corpus/generate.py` (~line 416-419) is
a **static assignment today** — keep it static. Build the enriched candidate list from a
**fixed, deterministic source** (the scenario ids in `distributions.SCENARIOS`, in their
declared order), NOT by sampling. Do not touch `decision_chosen` (stays `scenario_id`).

**If the mock regression moves at all, you perturbed the RNG — STOP and flag.** Do not
"re-baseline" the headline; that is an owner/Claude decision, not a fix.

## Boundaries (hard)
- `packages/corpus/` + a `packages/verdict/tests/` oracle test only. **NEVER touch
  `packages/schema/`, `fixtures/golden/`, `docs/METHOD.md`, `docs/LIMITATIONS.md`, or the
  paid path.** The 23 golden fixtures are pinned files (not regenerated) — they must not
  change.
- **No paid runs, no credit.** This is a deterministic corpus change + tests. The actual
  preservation-under-divergence *number* comes from a LATER owner-gated paid run with the
  enriched corpus — explicitly OUT of scope here.
- Green + `ruff check packages/` clean.

## The change
In the route branch of `generate.py` (decision_kind == route, i == 0):
- `decision_candidates` becomes the full set of registered scenario ids plus `"other"`,
  deterministically (e.g. `[*ALL_SCENARIO_IDS, "other"]` where `ALL_SCENARIO_IDS` is
  derived once from `distributions.SCENARIOS`). The trace's own `scenario_id` must be in
  the set. No `rng` call.
- `decision_chosen` is UNCHANGED (`scenario.scenario_id`).

## Tests (TDD, write first)
1. **Headline byte-identical (the gate):** `run_experiments.py --n 250 --seed 0` still
   gives **0.57%** and `--seed 8` **0.55%**, with identical findings/verdicts/n_divergent
   /n_truncated. (A test that regenerates the corpus for a fixed seed and asserts route
   `decision_chosen` unchanged + the per-trace priced totals unchanged is the tight
   version.)
2. **Candidates enriched:** every route span's `decision_candidates` now contains the
   trace's `scenario_id`, at least two OTHER registered scenario ids, and `"other"`.
3. **Oracle now decidable:** a `fork_oracle` unit test — a route fork from intent A to a
   different registered scenario B (whose `requires_mutation` differs) returns **False**
   (decidable), not `None`. This proves the enriched candidates unblock the oracle.

## Acceptance
- Route candidates enriched deterministically; `decision_chosen` and the deterministic
  headline (0.57%/0.55%, findings, verdicts) **byte-identical** — proven, not asserted.
- The oracle returns a non-`None` verdict for a registered-scenario route fork.
- `fixtures/golden/`, `schema/`, `METHOD.md`, `LIMITATIONS.md` diffs empty; no paid run.
- Suite green, ruff clean. Delivery report: the before/after mock numbers (proving no
  drift) and the enriched candidate set.

## After this merges (owner/Claude, not you)
A small owner-gated paid re-probe/run with the enriched corpus generates real
registered-scenario forks; `preservation_divergence` then yields the modeled number,
which Claude lands in METHOD with its caveats. The oracle is already built; this brief
only widens the door.
