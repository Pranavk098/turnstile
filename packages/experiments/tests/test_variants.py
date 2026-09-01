"""Tests for VARIANTS / RESERVED_VARIANTS (packages/experiments, PRD Sec.8.2).

The matrix ``VARIANTS`` is the EXECUTABLE set (what the replay engine actually
applies); ``RESERVED_VARIANTS`` holds honestly-specified remedies the replay
path can't execute yet. See turnstile_experiments.variants + guard.
"""
from __future__ import annotations

from turnstile_schema import VariantSpec

from turnstile_experiments import RESERVED_VARIANTS, VARIANTS
from turnstile_experiments.guard import assert_variant_executable, unimplemented_fields


def test_executable_matrix_is_model_routing_only():
    # Only model_routing is applied on the replay path today, so the runnable
    # matrix is exactly that one lever -- not six, five of which are no-ops.
    assert set(VARIANTS) == {"model_routing_gpt5_nano"}
    assert VARIANTS["model_routing_gpt5_nano"] == VariantSpec(model_routing={"route": "gpt-5-nano"})


def test_every_executable_variant_is_actually_executable():
    for name, variant in VARIANTS.items():
        assert_variant_executable(name, variant)  # must not raise


def test_reserved_variants_are_the_pending_remedies():
    assert set(RESERVED_VARIANTS) == {
        "context_window_8", "prefix_caching_on", "retrieval_threshold_0_8",
        "tts_chunking_sentence", "escalation_threshold_0_85",
    }
    # Each reserved variant sets a field replay cannot execute yet.
    for name, variant in RESERVED_VARIANTS.items():
        assert unimplemented_fields(variant), f"{name} should set an unimplemented field"


def test_every_variant_isolates_exactly_one_knob():
    knob_fields = [
        "model_routing", "context_strategy", "prefix_caching",
        "retrieval_policy", "tts_chunking", "escalation_policy", "tool_batching",
    ]
    for name, variant in {**VARIANTS, **RESERVED_VARIANTS}.items():
        set_fields = [f for f in knob_fields if getattr(variant, f) is not None]
        assert len(set_fields) == 1, f"{name} sets {set_fields}, expected exactly one"
