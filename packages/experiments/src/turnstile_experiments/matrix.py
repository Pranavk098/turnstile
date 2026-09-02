"""``run_matrix`` -- the experiment-matrix driver.

Runs ``turnstile_replay.experiment(corpus, variant)`` once per ``VariantSpec``
in ``variants``, all under a single ``DecisionBackend`` for the whole matrix.
Defaults to the free ``turnstile_replay.MockBackend`` (NO live API call); a
real backend (e.g. ``turnstile_experiments.OpenAIBackend``, itself gated
behind ``TURNSTILE_ALLOW_PAID=1``) can be injected via ``backend=``.
"""
from __future__ import annotations

from turnstile_schema import ExperimentResult, PricedTrace, VariantSpec
from turnstile_replay import DecisionBackend, MockBackend, experiment, get_backend, set_backend

from turnstile_experiments.guard import assert_backend_executable, assert_variant_executable


def run_matrix(
    corpus: list[PricedTrace],
    variants: dict[str, VariantSpec],
    backend: DecisionBackend | None = None,
) -> dict[str, ExperimentResult]:
    """Run ``experiment(corpus, variant)`` for every ``(name, variant)`` in
    ``variants``, under ``backend`` (``MockBackend()`` -- free, no network --
    if ``backend`` is ``None``). The previously-installed backend is always
    restored afterward (even on error), so calling this never leaks a backend
    change into unrelated code.

    Refuses (``NotImplementedError``) any variant setting a field the replay
    backend does not apply -- including re-pricing-executable fields, which
    must go through ``run_repricing_matrix`` instead (otherwise the backend
    would replay them as the silent zero-delta no-op ``guard`` exists to
    prevent)."""
    for name, variant in variants.items():
        assert_variant_executable(name, variant)
        assert_backend_executable(name, variant)

    previous = get_backend()
    set_backend(backend if backend is not None else MockBackend())
    try:
        return {name: experiment(corpus, variant) for name, variant in variants.items()}
    finally:
        set_backend(previous)
