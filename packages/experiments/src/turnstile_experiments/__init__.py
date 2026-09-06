"""turnstile_experiments — the deterministic headline pipeline + the extras.

The CORE (imported eagerly below) is the deterministic recoverable-margin path
`run_experiments.py` needs: variants/guard, transforms/repricing, matrix +
checkpoint, margin, manifest, cost_estimate, baselines, openai_backend.

The EXTRAS (`bargein_report`, `coverage`, `sweeps`) are loaded LAZILY via
``__getattr__`` (PEP 562): ``bargein_report`` drags in the acoustic stack
(``turnstile_agent`` → ``turnstile_otel`` → ``opentelemetry-sdk``), and the
free deterministic run should not have to import — or install — that spike
stack just to compute the 0.57% headline (audit Task-2 A). Every public name
stays importable; the acoustic/detector modules are only imported the first
time one of their names is actually accessed.
"""
from turnstile_experiments.baselines import compute_baselines
from turnstile_experiments.checkpoint_runner import (
    CheckpointStore,
    run_experiment_checkpointed,
    run_matrix_checkpointed,
    run_matrix_checkpointed_detailed,
)
from turnstile_experiments.cost_estimate import estimate_cost
from turnstile_experiments.guard import (
    BACKEND_APPLIED_VARIANT_FIELDS,
    IMPLEMENTED_VARIANT_FIELDS,
    applied_fields,
    assert_backend_executable,
    assert_variant_executable,
    unimplemented_fields,
)
from turnstile_experiments.manifest import build_manifest
from turnstile_experiments.margin import GATE_MIN_PRESERVATION_RATE, recoverable_margin
from turnstile_experiments.matrix import run_matrix
from turnstile_experiments.openai_backend import OpenAIBackend
from turnstile_experiments.repricing import (
    CONDITIONAL_SAVINGS_LABEL,
    RepricingResult,
    run_repricing_experiment,
    run_repricing_matrix,
)
from turnstile_experiments.transforms import REPRICING_TRANSFORMS, apply_variant_transform
from turnstile_experiments.variants import (
    HARNESS_VARIANTS,
    REPRICING_VARIANTS,
    RESERVED_VARIANTS,
    VARIANTS,
)

# Lazy extras: name -> submodule. Kept out of the eager import graph so the
# deterministic headline path imports without the acoustic spike stack.
_LAZY_NAMES = {
    "BARGE_IN_RATES": "bargein_report",
    "LEAD_CAP_VALUES": "bargein_report",
    "run_bargein_report": "bargein_report",
    "detector_coverage": "coverage",
    "run_d7_barge_in_sweep": "sweeps",
    "run_d8_silence_sweep": "sweeps",
    "run_sweeps": "sweeps",
}


def __getattr__(name: str):  # PEP 562
    submodule = _LAZY_NAMES.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = value  # cache: subsequent access skips __getattr__
    return value


__all__ = [
    "compute_baselines",
    "BARGE_IN_RATES",
    "LEAD_CAP_VALUES",
    "run_bargein_report",
    "VARIANTS",
    "REPRICING_VARIANTS",
    "HARNESS_VARIANTS",
    "RESERVED_VARIANTS",
    "run_matrix",
    "run_repricing_experiment",
    "run_repricing_matrix",
    "RepricingResult",
    "CONDITIONAL_SAVINGS_LABEL",
    "REPRICING_TRANSFORMS",
    "apply_variant_transform",
    "run_matrix_checkpointed",
    "run_matrix_checkpointed_detailed",
    "run_experiment_checkpointed",
    "CheckpointStore",
    "build_manifest",
    "assert_variant_executable",
    "assert_backend_executable",
    "applied_fields",
    "unimplemented_fields",
    "IMPLEMENTED_VARIANT_FIELDS",
    "BACKEND_APPLIED_VARIANT_FIELDS",
    "recoverable_margin",
    "GATE_MIN_PRESERVATION_RATE",
    "OpenAIBackend",
    "estimate_cost",
    "detector_coverage",
    "run_d7_barge_in_sweep",
    "run_d8_silence_sweep",
    "run_sweeps",
]
