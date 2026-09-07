# Brief — experiments paid-path hardening: fork-persistence + truncation policy

**Base:** `wave0-foundation` @ `66fe8ed`. Branch `opencode/wave2-exp-hardening`.
Reviewed + merged by Claude. **Build TDD. No paid runs** (tests use fake backends).

## Why these two are ONE branch (not two parallel)
Both edit the same paid-path files (`ReplayedDecision`, `Trial`, the experiments
aggregation, `run_experiments.py`), so splitting them into parallel branches would
guarantee merge conflicts. Do them in this one branch, in order.

## Boundaries (hard)
- Lanes: `packages/replay/` + `packages/experiments/` + `packages/stats/` (aggregation)
  only. **NEVER touch `packages/schema/`, `fixtures/golden/`, `docs/METHOD.md`,
  `docs/LIMITATIONS.md`.** These are experiment-*result* fields, not frozen `Trace`
  schema — do not add them to the schema contracts.
- **No new paid spend.** The gated OpenAI path stays exactly as gated; you exercise the
  new fields with fake/mock backends in tests only.
- The deterministic mock path must be **unaffected**: `run_experiments.py --n 250
  --seed 0` still reproduces **0.57%**, seed 8 still **0.55%**, 0 divergent, 0 truncated.
  A regression there is a STOP-and-flag.
- Green + `ruff check packages/` clean.

## Item 1 — Fork-persistence (self-documenting forks)
Today a divergent (forked) trial records only `status="divergent"`; the forked
decision label + text are lost, which is why `turnstile_experiments.preservation_divergence`
needs a `--sidecar`. Persist them so every paid run self-documents its forks.
- Thread `finish_reason` and the replayed decision's parsed `decision_chosen` +
  `output_text` from the backend to the trial record. `OpenAIBackend` already computes
  `finish_reason` (it only logs it today) — **return it on `ReplayedDecision`** (new
  optional field, defaulting `None`; `MockBackend` leaves it `None`).
- For **divergent** trials, carry `forked_label` (the replayed `decision_chosen`),
  `forked_text` (the replayed `output_text`), and `finish_reason` into the result
  JSON's divergent records / `divergent_exemplars` and into the checkpoint record.
- Make `preservation_divergence.analyze_forks` read `forked_label` **directly from the
  result JSON** when present; keep `--sidecar` as an accepted legacy override.
- **Acceptance:** a fork-inducing fake backend produces a result JSON whose divergent
  records carry `forked_label`/`forked_text`; `analyze_forks` computes with **no
  sidecar**; the checkpoint round-trips the fields. TDD: write the persistence + read
  tests first.

## Item 2 — Truncation policy: flag-and-exclude (owner-decided)
A completion with `finish_reason == "length"` is a clipped/unfinished reply; its parsed
decision is untrustworthy. **Policy (decided): flag-and-exclude — never raise the cap.**
- Mark such a trial `truncated` (a boolean field on the trial record, or a distinct
  status — your call, but it must be distinguishable from `divergent` and `ok`).
- **Exclude truncated trials from every aggregate** (preservation rate, divergence rate,
  recoverable margin): out of both numerator and denominator. Count them as `n_truncated`
  and list them in a `truncated_exemplars` block with their `finish_reason` +
  reasoning/content split. Never silently score a clipped trial.
- Do NOT raise `max_completion_tokens`. (At 2/1,734 observed, exclusion is correct and
  cheap; a bigger cap doesn't make a clipped reply trustworthy.)
- **Acceptance:** a fake backend returning `finish_reason="length"` yields a trial that
  is excluded from aggregates and listed under `n_truncated`/`truncated_exemplars`; the
  margin/preservation numbers are computed over the non-truncated set. TDD first.

## Acceptance (whole branch)
- Deterministic mock regression unmoved (0.57%/0.55%, 0 divergent, 0 truncated).
- Divergent trials self-document (`forked_label`/`forked_text`/`finish_reason`);
  `analyze_forks` needs no sidecar on a fresh result.
- Truncated trials excluded + listed, never folded.
- No schema/golden/METHOD/LIMITATIONS diff; suite green; ruff clean.
- Delivery report: the fields added, and the mock-regression numbers proving no drift.
