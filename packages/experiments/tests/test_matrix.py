"""Tests for run_matrix (packages/experiments)."""
from __future__ import annotations

import pytest

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_replay import MockBackend, get_backend, reset_backend, set_backend
from turnstile_schema import ExperimentResult, VariantSpec, load_rates

from turnstile_experiments import REPRICING_VARIANTS, VARIANTS, run_matrix

RATES = load_rates("pricing/rates.yaml")


def _small_corpus(n: int = 15, seed: int = 0):
    return [price_trace(t, RATES) for t in generate_corpus(n, seed)]


def test_returns_one_experiment_result_per_variant():
    corpus = _small_corpus()
    matrix = run_matrix(corpus, VARIANTS)
    assert set(matrix.keys()) == set(VARIANTS.keys())
    for result in matrix.values():
        assert isinstance(result, ExperimentResult)


def test_default_backend_is_free_mock_backend_no_network():
    """No `backend=` -> MockBackend, never a live call. Grep-verifiable: this
    test never sets TURNSTILE_ALLOW_PAID and never imports OpenAIBackend."""
    reset_backend()
    corpus = _small_corpus(n=5)
    run_matrix(corpus, {"model_routing_gpt5_nano": VARIANTS["model_routing_gpt5_nano"]})
    # run_matrix restores whatever was installed before the call.
    assert isinstance(get_backend(), MockBackend)


def test_previous_backend_is_restored_after_call():
    reset_backend()
    sentinel = MockBackend()
    set_backend(sentinel)
    corpus = _small_corpus(n=5)
    run_matrix(corpus, {"model_routing_gpt5_nano": VARIANTS["model_routing_gpt5_nano"]},
               backend=MockBackend())
    assert get_backend() is sentinel
    reset_backend()


def test_custom_backend_is_actually_used():
    calls = []

    def spy_backend(context, original_span, variant):
        calls.append(original_span.span_id)
        return MockBackend()(context, original_span, variant)

    corpus = _small_corpus(n=5)
    run_matrix(corpus, {"model_routing_gpt5_nano": VARIANTS["model_routing_gpt5_nano"]},
               backend=spy_backend)
    assert len(calls) > 0
    reset_backend()


def test_reserved_variants_fail_loudly_instead_of_running_as_no_ops():
    """A variant whose field no runner executes (tts_chunking -- the barge-in
    acoustic track owns it) would replay as a zero-delta no-op (and, on
    --paid, spend real credit doing so). run_matrix must refuse it at
    experiment start, not silently return an identity result."""
    corpus = _small_corpus(n=5)
    with pytest.raises(NotImplementedError):
        run_matrix(corpus, {"tts_chunking_sentence": VariantSpec(tts_chunking="sentence")})
    reset_backend()


def test_repricing_variants_fail_loudly_on_the_backend_path():
    """Section A: prefix_caching executes via the deterministic re-pricing
    runner, not the backend -- here it would replay as the silent zero-delta
    no-op guard exists to prevent, so run_matrix must refuse it."""
    corpus = _small_corpus(n=5)
    with pytest.raises(NotImplementedError, match="run_repricing_matrix"):
        run_matrix(corpus, REPRICING_VARIANTS)
    reset_backend()
