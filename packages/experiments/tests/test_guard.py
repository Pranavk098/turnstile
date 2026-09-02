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


@pytest.mark.parametrize("field, value", [
    ("retrieval_policy", "threshold:0.8"),
    ("tts_chunking", "sentence"),
])
def test_reserved_fields_raise(field, value):
    v = VariantSpec(**{field: value})
    assert unimplemented_fields(v) == {field}
    with pytest.raises(NotImplementedError, match=field):
        assert_variant_executable("reserved", v)


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


def test_mixed_variant_raises_on_the_unsupported_field():
    # Even with an executable model_routing present, an unsupported field must
    # still fail loudly rather than partially run.
    v = VariantSpec(model_routing={"route": "gpt-5-nano"}, retrieval_policy="threshold:0.8")
    assert applied_fields(v) == {"model_routing"}
    assert unimplemented_fields(v) == {"retrieval_policy"}
    with pytest.raises(NotImplementedError, match="retrieval_policy"):
        assert_variant_executable("mixed", v)
    with pytest.raises(NotImplementedError, match="retrieval_policy"):
        assert_backend_executable("mixed", v)


def test_empty_variant_raises():
    with pytest.raises(NotImplementedError, match="no fields"):
        assert_variant_executable("empty", VariantSpec())


def test_field_sets_partition_the_schema():
    assert IMPLEMENTED_VARIANT_FIELDS == {
        "model_routing", "context_strategy", "prefix_caching",
        "tool_batching", "escalation_policy"}
    assert BACKEND_APPLIED_VARIANT_FIELDS == {"model_routing"}
    assert BACKEND_APPLIED_VARIANT_FIELDS < IMPLEMENTED_VARIANT_FIELDS
    for field in ("context_strategy", "prefix_caching", "tool_batching", "escalation_policy"):
        assert field not in RESERVED_VARIANT_FIELDS
    assert IMPLEMENTED_VARIANT_FIELDS.isdisjoint(RESERVED_VARIANT_FIELDS)
