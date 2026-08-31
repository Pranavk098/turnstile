"""D7/D8 sensitivity sweeps (docs/DEMO.md "Detector 8 as a hypothesis, not a
claim"; docs/CORPUS.md Constraint 3) -- the honest alternative to tuning the
generator.

Detector 7 (barge-in) and Detector 8 (silence tax) are Tier-2/"modeled
acoustics" detectors (docs/CORPUS.md): their dollar magnitude on the synthetic
corpus depends on a generator assumption, not a measurement. Rather than
assert a single number, this module re-runs the full price -> adjudicate ->
detect pipeline across a plausible range of ONE named generator parameter per
detector, holding seed + n fixed, and reports the detector's response as a
curve. Nothing here changes what the generator samples for a GIVEN parameter
value -- it only varies that one named input across runs, exactly the
Constraint-3 treatment docs/CORPUS.md already gives D7, extended to D8.

Two named parameters swept, one per detector:

* D7 -- ``turnstile_corpus.distributions.BARGE_IN_RATE``, threaded through the
  existing ``generate_corpus(..., barge_in_rate=...)`` override (Constraint 3
  is already built for this).
* D8 -- ``turnstile_corpus.distributions.INTER_TURN_GAP_MEDIAN_MS``, the
  median of the lognormal caller-response-latency gap (the "inter-turn gap,"
  6a in distributions.py, cited to Stivers et al., PNAS 2009's cross-
  linguistic modal turn-taking gap of ~200ms -- the same paper documents
  substantial variation in that modal gap across languages/cultures, which is
  what makes this specific constant the meaningful D8 knob to sweep: its
  200ms default sits right at ``SILENCE_GAP_THRESHOLD_MS`` (the detector's own
  200ms noise floor, d08_silence_tax.py), so this is the parameter whose
  value actually shifts what fraction of turns' leading gap crosses into
  "real dead air" -- unlike ``PROCESSING_LATENCY_MEDIAN_MS`` (6b), whose
  ~1100ms median is so far above the threshold that varying it moves D8's
  waste-per-finding but leaves the finding COUNT (and therefore D8's share of
  total findings) essentially flat, which was verified empirically before
  picking this parameter over that one. This constant has no existing CLI/
  kwarg override the way ``BARGE_IN_RATE`` does, so this module monkeypatches
  the module-level constant on ``turnstile_corpus.distributions`` for the
  duration of one corpus generation and restores it immediately after --
  functionally identical to a real override, without adding one to the
  corpus package (this task's scope is packages/experiments only). This is
  the SAME single named parameter for every trace in a given sweep point --
  nothing else about the generator changes.

Both sweeps use the shared price -> compute_baselines -> adjudicate -> detect
pipeline, the same pattern ``turnstile_experiments.coverage.detector_coverage``
already uses.
"""
from __future__ import annotations

from typing import TypedDict

from turnstile_corpus import distributions as corpus_dist
from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_schema import PricedTrace, RateTable
from turnstile_detectors import detect
from turnstile_verdict import adjudicate

from turnstile_experiments.baselines import compute_baselines

# Modest defaults so a sweep (5 corpus regenerations x n traces, per detector)
# runs in reasonable time with no network/OpenAI calls -- pure pipeline
# re-runs. Documented in sweeps-report.md alongside the results.
DEFAULT_N = 80
DEFAULT_SEED = 7

# D7 range: centered on the shipped default (BARGE_IN_RATE = 0.15,
# distributions.py, telli.com citation), spanning roughly half to double it --
# a plausible band around the cited "15-20% of callers talk over the agent"
# figure without leaving the region a real fleet could plausibly land in.
D7_BARGE_IN_RATES: list[float] = [0.05, 0.10, 0.15, 0.20, 0.30]

# D8 range: centered on the shipped default (INTER_TURN_GAP_MEDIAN_MS =
# 200ms, distributions.py, Stivers et al. PNAS 2009 cross-linguistic modal
# turn-taking gap), spanning roughly half to 2.25x it. The cited paper itself
# reports meaningful cross-language/cross-cultural variation around that
# pooled ~200ms mode rather than a single universal constant, so a band of
# this width -- not a single asserted figure -- is the honest reading of that
# citation; no new precise per-point figure is claimed beyond the source.
D8_INTER_TURN_GAP_MEDIAN_MS: list[float] = [100.0, 150.0, 200.0, 300.0, 450.0]


class SweepPoint(TypedDict):
    param_value: float
    detector_findings: int
    detector_waste_usd: float
    total_findings: int
    detector_share_of_findings: float


def _pipeline_metrics(traces, rates: RateTable, class_id: int) -> SweepPoint:
    """Run price -> compute_baselines -> adjudicate -> detect over ``traces``
    and summarize class ``class_id``'s findings/waste and share of all
    findings across every detector class (same pipeline shape as
    ``turnstile_experiments.detector_coverage``)."""
    corpus: list[PricedTrace] = [price_trace(t, rates) for t in traces]
    baselines = compute_baselines(corpus)

    total_findings = 0
    class_findings = 0
    class_waste_usd = 0.0
    for pt in corpus:
        verdict = adjudicate(pt)
        for finding in detect(pt, verdict, baselines):
            total_findings += 1
            if finding.class_id == class_id:
                class_findings += 1
                class_waste_usd += finding.waste_usd

    share = class_findings / total_findings if total_findings else 0.0
    return SweepPoint(
        param_value=0.0,  # filled in by the caller
        detector_findings=class_findings,
        detector_waste_usd=class_waste_usd,
        total_findings=total_findings,
        detector_share_of_findings=share,
    )


def run_d7_barge_in_sweep(
    rates: RateTable,
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    values: list[float] | None = None,
) -> list[SweepPoint]:
    """D7 sensitivity sweep: vary ONLY ``BARGE_IN_RATE`` across ``values``,
    n and seed fixed, via the existing ``generate_corpus(barge_in_rate=...)``
    override. Returns one ``SweepPoint`` per value, in the given order."""
    points: list[SweepPoint] = []
    for rate in values if values is not None else D7_BARGE_IN_RATES:
        traces = generate_corpus(n, seed, barge_in_rate=rate)
        point = _pipeline_metrics(traces, rates, class_id=7)
        point["param_value"] = rate
        points.append(point)
    return points


def run_d8_silence_sweep(
    rates: RateTable,
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    values: list[float] | None = None,
) -> list[SweepPoint]:
    """D8 sensitivity sweep: vary ONLY ``INTER_TURN_GAP_MEDIAN_MS`` across
    ``values``, n and seed fixed. ``generate_corpus`` has no kwarg for this
    parameter, so it is monkeypatched on ``turnstile_corpus.distributions``
    for the duration of each corpus generation and restored immediately after
    -- everything else about the generator (all other named distributions)
    stays exactly as shipped."""
    original = corpus_dist.INTER_TURN_GAP_MEDIAN_MS
    points: list[SweepPoint] = []
    try:
        for median_ms in values if values is not None else D8_INTER_TURN_GAP_MEDIAN_MS:
            corpus_dist.INTER_TURN_GAP_MEDIAN_MS = median_ms
            traces = generate_corpus(n, seed)
            point = _pipeline_metrics(traces, rates, class_id=8)
            point["param_value"] = median_ms
            points.append(point)
    finally:
        corpus_dist.INTER_TURN_GAP_MEDIAN_MS = original
    return points


def run_sweeps(
    rates: RateTable,
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Both sweeps, packaged for JSON output (``sweeps.json``)."""
    return {
        "n": n,
        "seed": seed,
        "d7_barge_in_sweep": {
            "parameter": "turnstile_corpus.distributions.BARGE_IN_RATE",
            "class_id": 7,
            "points": run_d7_barge_in_sweep(rates, n=n, seed=seed),
        },
        "d8_silence_sweep": {
            "parameter": "turnstile_corpus.distributions.INTER_TURN_GAP_MEDIAN_MS",
            "class_id": 8,
            "points": run_d8_silence_sweep(rates, n=n, seed=seed),
        },
    }
