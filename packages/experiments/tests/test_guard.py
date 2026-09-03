"""Tests for the fail-loud variant guard (turnstile_experiments.guard): a
variant that sets a field no replay backend applies must raise at experiment
start, not run as a silent zero-delta no-op."""
from __future__ import annotations

import pytest

from turnstile_schema import VariantSpec

from turnstile_experiments.guard import (
    BACKEND_APPLIED_VARIANT_FIELDS,
    IMPLEMENTED_VARIANT_FIELDS,
    RESERVED_VARIANT_FIELDS,
    applied_fields,
    assert_backend_executable,
    assert_variant_executable,
    unimplemented_fields,
)


def test_model_routing_is_executable():
    v = VariantSpec(model_routing={"route": "gpt-5-nano"})
    assert applied_fields(v) == {"model_routing"}
    assert unimplemented_fields(v) == set()
    assert_variant_executable("model_routing_gpt5_nano", v)  # does not raise
    assert_backend_executable("model_routing_gpt5_nano", v)  # does not raise


@pytest.mark.parametrize("field, value", [])
def test_reserved_fields_raise(field, value):
    v = VariantSpec(**{field: value})
    assert unimplemented_fields(v) == {field}
    with pytest.raises(NotImplementedError, match=field):
        assert_variant_executable("reserved", v)


def test_no_reserved_fields_remain():
    # Batch 2 T1: tts_chunking gained a measured execution path on the
    # barge-in harness -- every VariantSpec field now executes somewhere, so
    # the reserved set is empty and nothing can silently no-op.
    assert RESERVED_VARIANT_FIELDS == set()
    one_knob_specs = {
        "model_routing": VariantSpec(model_routing={"route": "gpt-5-nano"}),
        "context_strategy": VariantSpec(context_strategy="window:8"),
        "prefix_caching": VariantSpec(prefix_caching=True),
        "tool_batching": VariantSpec(tool_batching=True),
        "escalation_policy": VariantSpec(escalation_policy="threshold:0.85"),
        "retrieval_policy": VariantSpec(retrieval_policy="threshold:0.8"),
        "tts_chunking": VariantSpec(tts_chunking="clause"),
    }
    assert set(one_knob_specs) == set(VariantSpec.model_fields)
    for field, v in one_knob_specs.items():
        assert_variant_executable(field, v)  # does not raise


def test_mixed_variant_still_refuses_the_backend_path():
    # With every field implemented somewhere, a variant mixing the backend
    # knob with a non-backend field must still refuse the BACKEND path
    # wholesale -- no partial execution.
    v = VariantSpec(model_routing={"route": "gpt-5-nano"}, tts_chunking="clause")
    with pytest.raises(NotImplementedError, match="tts_chunking"):
        assert_backend_executable("mixed", v)


def test_tts_chunking_executes_via_the_harness_not_the_backend():
    # D6/D7's remedy runs on the barge-in harness (measured, real Piper) --
    # never the replay backend, where it would be a silent zero-delta no-op.
    v = VariantSpec(tts_chunking="clause")
    assert applied_fields(v) == {"tts_chunking"}
    assert unimplemented_fields(v) == set()
    assert_variant_executable("tts_chunking_clause", v)  # does not raise
    with pytest.raises(NotImplementedError, match="barge-in harness"):
        assert_backend_executable("tts_chunking_clause", v)


def test_prefix_caching_implemented_via_repricing_not_on_the_backend():
    # Section A: a deterministic re-pricing transform exists, so the field is
    # implemented -- but the replay backend does not apply it, and handing it
    # to the backend path would be the silent zero-delta no-op guard exists
    # to prevent. It must be run via run_repricing_matrix instead.
    v = VariantSpec(prefix_caching=True)
    assert applied_fields(v) == {"prefix_caching"}
    assert unimplemented_fields(v) == set()
    assert_variant_executable("prefix_caching_on", v)  # does not raise
    with pytest.raises(NotImplementedError, match="run_repricing_matrix"):
        assert_backend_executable("prefix_caching_on", v)


def test_empty_variant_raises():
    with pytest.raises(NotImplementedError, match="no fields"):
        assert_variant_executable("empty", VariantSpec())


def test_field_sets_partition_the_schema():
    assert IMPLEMENTED_VARIANT_FIELDS == set(VariantSpec.model_fields)
    assert BACKEND_APPLIED_VARIANT_FIELDS == {"model_routing"}
    assert BACKEND_APPLIED_VARIANT_FIELDS < IMPLEMENTED_VARIANT_FIELDS
    assert RESERVED_VARIANT_FIELDS == set()
