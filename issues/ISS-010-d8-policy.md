# ISS-010: Live D8 policy — force-ABSENT (DECIDED 2026-09-20)

- Status: implemented 2026-09-20 (force-ABSENT wired in the ingest coverage envelope; GATES.md + LIMITATIONS.md updated). Upper-bound follow-up specced below.
- Source: c2_d8_absent (0.59); over-report assumption 0.72; risk 1.78 (highest)
- Problem: union==sum on non-overlap recorders systematically over-reports silence;
  D8 is ~82% of corpus findings, mostly modeled-gap artifact (`d08:26-31`; GATES:17-27).
- Jev verdict: weak lean to force-ABSENT — not a decision, a coin flip with context.
- Proposal: YOU decide — force ABSENT until concurrency redesign, or show with Tier-2 tag.
- Accept when: decision recorded here + implemented + GATES.md updated.

## Decision (2026-09-20): force-ABSENT, gated on G1

Live D8 findings are forced ABSENT (hidden) until the recorder emits real
concurrency (the G1 concurrency redesign). Rationale:

- **Consistency with our own ruling.** `docs/GATES.md` G1 already states live D8
  "will systematically over-report silence/waste on real traffic" and that its
  results are "a demo of the detector, not a measurement." Showing live D8 —
  even tagged — would ship as a finding the very thing G1 says is not one.
- **This is directional bias, not uncertainty.** `union==sum` always over-reports
  (biased high), so a Tier-2 "modeled-data" tag mislabels the failure mode: tags
  communicate confidence/provenance, not "this number is inflated." With D8 at
  ~82% of findings, tagging launders a known-biased majority of output and puts
  the honest-measurement position at risk.
- **Low regret.** The coverage dropped is artifact, not signal; D8 still works as
  a demo on the overlap-bearing fixtures; it flips back on as a real measurement
  once G1 lands and recorders emit overlap.

Not chosen: Tier-2 tag (right only if the error were symmetric uncertainty — it
is not).

## Implementation (2026-09-20)

- `turnstile_detectors.d08_silence_tax.trace_has_span_overlap(trace)` — true
  only when some turn has **cross-stream** overlap (tts+playback collapsed into
  one "speech" stream, since they are co-timed by construction). No cross-stream
  overlap ⇒ the `union==sum` live-recorder signature.
- `turnstile_ingest.pipeline.describe_coverage(..., has_span_overlap=...)` —
  when telephony + acoustic are present but there is no cross-stream overlap, D8
  is labeled **ABSENT** (reason `NO_OVERLAP_REASON`), so its findings are
  excluded from the report like any absent class.
- Docs: `GATES.md` G1 + `LIMITATIONS.md §4` record the enforcement.
- Effect on current artifacts: **zero** — the synthetic sample (49/50) and the
  Retell call carry authored cross-stream concurrency, so they stay PRESENT; the
  gate is a latent guard that trips on real live-recorder traffic (and lifts
  itself once G1 lands).

## Follow-up (specced, not built): D8 as an honest UPPER BOUND

Reclaim D8 coverage *before* the G1 concurrency redesign without shipping a
biased point estimate.

- **Why valid.** With no overlap, `union == sum` and `silence = billed_wall −
  sum` is the *smallest* silence any real overlap could produce collapsed to
  its max: the reported silence is a true **ceiling**. "Silence tax ≤ X" is a
  correct statement, not a hedge — strictly more honest than a Tier-2 tag and
  more useful than hiding.
- **Shape.** On a no-overlap trace, instead of ABSENT, emit D8 as a bounded
  finding: `waste_usd` becomes `waste_usd_max`, verdict/label reads "upper
  bound — no concurrency data (G1)", and the dashboard renders `≤` with the
  same G1 provenance string. Never a point estimate, never summed into a
  headline as if measured.
- **Acceptance.** New Finding field or evidence flag `upper_bound: true`;
  dashboard shows `≤`; a test pins that a no-overlap trace yields a bounded D8
  (not ABSENT, not a point estimate); LIMITATIONS/GATES updated to describe the
  ceiling. Requires owner sign-off before building (changes what the dashboard
  shows).
