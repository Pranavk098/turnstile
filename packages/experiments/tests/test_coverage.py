"""Tests for detector_coverage (packages/experiments)."""
from __future__ import annotations

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_schema import load_rates

from turnstile_experiments import compute_baselines, detector_coverage

RATES = load_rates("pricing/rates.yaml")


def test_returns_class_id_to_count_mapping_sorted():
    corpus = [price_trace(t, RATES) for t in generate_corpus(20, seed=0)]
    baselines = compute_baselines(corpus)
    coverage = detector_coverage(corpus, baselines)

    assert isinstance(coverage, dict)
    for class_id, count in coverage.items():
        assert 1 <= class_id <= 10
        assert count > 0
    assert list(coverage.keys()) == sorted(coverage.keys())


def test_empty_corpus_yields_empty_coverage():
    assert detector_coverage([], compute_baselines([])) == {}
