"""Tests for VARIANTS (packages/experiments, PRD Sec.8.2)."""
from __future__ import annotations

from turnstile_schema import VariantSpec

from turnstile_experiments import VARIANTS


def test_exactly_six_variants():
    assert len(VARIANTS) == 6


def test_every_variant_isolates_exactly_one_knob():
    knob_fields = [
        "model_routing", "context_strategy", "prefix_caching",
        "retrieval_policy", "tts_chunking", "escalation_policy", "tool_batching",
    ]
    for name, variant in VARIANTS.items():
        set_fields = [f for f in knob_fields if getattr(variant, f) is not None]
        assert len(set_fields) == 1, f"{name} sets {set_fields}, expected exactly one"


def test_task_brief_examples_present():
    assert VARIANTS["model_routing_gpt5_nano"] == VariantSpec(model_routing={"route": "gpt-5-nano"})
    assert VARIANTS["context_window_8"] == VariantSpec(context_strategy="window:8")
    assert VARIANTS["prefix_caching_on"] == VariantSpec(prefix_caching=True)
    assert VARIANTS["retrieval_threshold_0_8"] == VariantSpec(retrieval_policy="threshold:0.8")
    assert VARIANTS["tts_chunking_sentence"] == VariantSpec(tts_chunking="sentence")
    assert VARIANTS["escalation_threshold_0_85"] == VariantSpec(escalation_policy="threshold:0.85")
