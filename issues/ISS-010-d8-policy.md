# ISS-010: Live D8 policy — force-ABSENT (DECIDED 2026-09-20)

- Status: decided (human call 2026-09-20: **force-ABSENT** over Tier-2 tag); implementation tracked as a follow-up.
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
is not). A future upper-bound presentation ("silence ≤ X; no concurrency data")
is the honest way to reclaim coverage before G1, tracked separately.

**Follow-up (implementation):** force live D8 → ABSENT in the live verdict path
and note it in `docs/LIMITATIONS.md`; `docs/GATES.md` G1 already documents the
underlying gate.
