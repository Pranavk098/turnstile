# Day 4 PRD — Quality: "pending" → "calibrated"

**Inherits `00-charter.md` in full.** Executor: OpenCode · Reviewer: Claude · Depends on:
Day-1 (surface), Day-2 (data) · Feeds: Day-6 (quality docs), Day-1 UI (surfacing).

## Objective
Move the model-graded quality dimensions from calibration-gated **no-ops** to either
**calibrated + shipped** or an **honest calibration report**, and make **barge-in
courtesy measured** on real audio.

## Connection (charter §5)
The quality block (charter §4) already surfaces beside cost on Day-1 and in Day-6 docs.
This day fills it in *without weakening the calibration gate* — the gate is the contract
that keeps the whole "honesty" thesis intact.

## Day-specific strict rules (add to charter §1) — the gate is inviolable
- A judge dimension MUST NOT emit a score unless the gate passes: **paid flag set AND a
  registered calibration with n ≥ 60, κ ≥ 0.75, ECE reported**. This MUST be proven by a
  dynamic test that tries to coax a score and fails.
- An uncalibrated or below-bar judge MUST render as **pending / not-measured**, never a
  numeral, and MUST NOT reach a headline or the beside-cost line.
- The reference-labeler MAY use the flagged small paid spend; it MUST be opt-in, logged,
  reproducible, and absent from CI. Human spot-checks MUST be recorded.
- The calibration set + labels MUST be committed (or a reproducible builder for them) so
  κ/ECE are re-derivable.

## Priority factors
### P0 — base case (MUST)
1. A **calibration harness + labeling tool** (CLI/HTML) to hand-label conversations.
2. A **≥ 60-conversation labeled set** (reference model pre-label + human spot-check).
3. **Cohen's κ + ECE** computed and committed as a calibration report (+ confusion matrix).
4. **Barge-in courtesy → measured** using the live agent's real Piper playback spans.

### P1 — build-on-top (SHOULD)
5. IF κ ≥ 0.75: ship the `faithfulness` / `answer_relevance` judges (paid-gated, **off by
   default**) and surface their scores beside cost with the correct tier.
6. Surface the calibration report (κ/ECE/matrix) in the docs (Day-6 hand-off).

### P2 — stretch (MAY)
7. Active-learning selection of the next labels. 8. A second human rater for inter-rater κ.

## Latency budget (charter §2, tightened)
- Deterministic quality eval MUST add **< 20 ms** per call to the existing path.
- A judge call (paid, off by default) that can exceed 1 s MUST run **async** (Day-3 jobs),
  never blocking `/api/evaluate`.

## Interfaces
`packages/quality/calibration` (extend): the labeling tool, a `Calibration` builder from
labels, a κ/ECE reporter. No change to the `evaluate_quality` signature or the gate's
public rules. Judges (if shipped) plug in behind `judge_may_score`.

## Acceptance criteria (EARS)
- IF a judge has no passing calibration, THEN `evaluate_quality` SHALL return
  score=None / tier=not_measured for it, even with the paid flag on. *(check: the coax
  test, run dynamically)*
- WHEN calibration yields κ < 0.75, the judges SHALL stay pending and the report SHALL
  state κ/ECE honestly. *(check: report contents + gate state)*
- WHERE playback spans exist, barge-in courtesy SHALL read **measured**. *(check: a
  real-audio call's rendered rubric)*
- WHEN κ ≥ 0.75 AND the paid flag is set, a judge SHALL emit a tiered score that appears
  beside cost. *(check: dynamic eval with a registered passing calibration)*

## Recursive loop — Day-4 dynamic checks (charter §3)
Run the calibration end-to-end; **dynamically** attempt to coax a score through every
illegitimate path (no flag, n<60, κ<0.75, ECE missing, unknown id) and confirm each is
refused; verify the live UI shows pending-as-text and (if shipped) calibrated-as-tiered;
verify barge-in courtesy reads measured on a real-audio call. Iterate until every gate
behaves exactly as specified. If 60 quality labels can't be produced within budget, that
is an **environmental blocker** — ship the harness + report the shortfall honestly; do
NOT lower the bar to "pass."

## Risks & mitigations
- Shipping an uncalibrated score as measured → the gate + coax test + reviewer-checks-first.
- Label quality → reference-model + human spot-check + recorded inter-rater agreement.
- Cost creep on the labeler → flagged, opt-in, logged, capped.

## Out of scope
New quality dimensions beyond the defined set; a full eval framework; per-scenario rubrics.

## Reviewer gate (Claude) — checked FIRST
No uncalibrated score can reach a headline/beside-cost (proven dynamically); κ/ECE report
committed + honest; barge-in courtesy measured; gate rules unchanged; $0 default path; CI green.
