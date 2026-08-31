"""Tests for run_matrix (packages/experiments)."""
from __future__ import annotations

from turnstile_corpus import generate_corpus
from turnstile_pricing import price_trace
from turnstile_replay import MockBackend, get_backend, reset_backend, set_backend
from turnstile_schema import ExperimentResult, load_rates

from turnstile_experiments import VARIANTS, run_matrix

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


def test_non_routing_variants_run_without_crashing():
    """MockBackend only differentiates on model_routing (task brief) -- the
    other five variants should still run cleanly (mostly excluded/identity),
    not raise."""
    corpus = _small_corpus(n=5)
    matrix = run_matrix(corpus, VARIANTS)
    for name in ("context_window_8", "prefix_caching_on", "retrieval_threshold_0_8",
                 "tts_chunking_sentence", "escalation_threshold_0_85"):
        result = matrix[name]
        assert isinstance(result, ExperimentResult)
