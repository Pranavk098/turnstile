"""Tests for VARIANTS / REPRICING_VARIANTS / RESERVED_VARIANTS (packages/
experiments, PRD Sec.8.2).

``VARIANTS`` is the backend-executable set (what the replay backend actually
applies); ``REPRICING_VARIANTS`` are Section-A remedies with a deterministic
transform (run via run_repricing_matrix, savings conditional); 
``RESERVED_VARIANTS`` holds honestly-specified remedies with NO execution
path yet. See turnstile_experiments.variants + guard.
"""
from __future__ import annotations

import pytest

from turnstile_schema import VariantSpec

from turnstile_experiments import REPRICING_VARIANTS, RESERVED_VARIANTS, VARIANTS
from turnstile_experiments.guard import (
    assert_backend_executable,
    assert_variant_executable,
    unimplemented_fields,
)


def test_executable_matrix_is_model_routing_only():
    # Only model_routing is applied on the replay backend today, so the
    # backend-run matrix is exactly that one lever -- not six, five of which
    # are no-ops. (Re-pricing remedies live in REPRICING_VARIANTS.)
    assert set(VARIANTS) == {"model_routing_gpt5_nano"}
    assert VARIANTS["model_routing_gpt5_nano"] == VariantSpec(model_routing={"route": "gpt-5-nano"})


def test_every_executable_variant_is_actually_executable():
    for name, variant in VARIANTS.items():
        assert_variant_executable(name, variant)  # must not raise
        assert_backend_executable(name, variant)  # must not raise


def test_repricing_variants_have_a_transform_but_no_backend_path():
    assert set(REPRICING_VARIANTS) == {
        "context_window_8", "prefix_caching_on", "tool_batching_on",
        "escalation_threshold_0_85"}
    assert REPRICING_VARIANTS["context_window_8"] == VariantSpec(context_strategy="window:8")
    assert REPRICING_VARIANTS["prefix_caching_on"] == VariantSpec(prefix_caching=True)
    assert REPRICING_VARIANTS["tool_batching_on"] == VariantSpec(tool_batching=True)
    assert REPRICING_VARIANTS["escalation_threshold_0_85"] == VariantSpec(
        escalation_policy="threshold:0.85")
    for name, variant in REPRICING_VARIANTS.items():
        assert_variant_executable(name, variant)  # transform exists...
        with pytest.raises(NotImplementedError, match="run_repricing_matrix"):
            assert_backend_executable(name, variant)  # ...but never run it here


def test_reserved_variants_are_the_pending_remedies():
    assert set(RESERVED_VARIANTS) == {
        "retrieval_threshold_0_8", "tts_chunking_sentence",
    }
    # Each reserved variant sets a field no runner can execute yet.
    for name, variant in RESERVED_VARIANTS.items():
        assert unimplemented_fields(variant), f"{name} should set an unimplemented field"


def test_every_variant_isolates_exactly_one_knob():
    knob_fields = [
        "model_routing", "context_strategy", "prefix_caching",
        "retrieval_policy", "tts_chunking", "escalation_policy", "tool_batching",
    ]
    for name, variant in {**VARIANTS, **REPRICING_VARIANTS, **RESERVED_VARIANTS}.items():
        set_fields = [f for f in knob_fields if getattr(variant, f) is not None]
        assert len(set_fields) == 1, f"{name} sets {set_fields}, expected exactly one"
