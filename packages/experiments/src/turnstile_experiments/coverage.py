"""``detector_coverage`` -- which of the ten detector classes fire on a
corpus, and how many findings each produces. An OBSERVATION, not a claim:
the corpus generator (``turnstile_corpus``) has zero import of
``turnstile_detectors`` (docs/CORPUS.md Constraint 2, "do not tune to the
detectors") -- whatever comes out here is whatever the sampled distributions
happened to produce, reported as-is.
"""
from __future__ import annotations

from collections import Counter

from turnstile_detectors import detect
from turnstile_schema import Baselines, PricedTrace
from turnstile_verdict import adjudicate


def detector_coverage(corpus: list[PricedTrace], baselines: Baselines) -> dict[int, int]:
    """``class_id -> finding count`` over every trace in ``corpus``, keys
    sorted ascending. A ``class_id`` with zero findings does not appear."""
    counts: Counter[int] = Counter()
    for pt in corpus:
        verdict = adjudicate(pt)
        for finding in detect(pt, verdict, baselines):
            counts[finding.class_id] += 1
    return dict(sorted(counts.items()))
