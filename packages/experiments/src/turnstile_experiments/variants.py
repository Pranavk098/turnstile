"""The replay variant space (PRD Sec.8.2), split by execution path.

``VARIANTS`` is the EXECUTABLE matrix for the REPLAY BACKEND -- variants the
backend applies for real, so their trials are genuine measurements. Today
that is exactly the ``model_routing`` lever: ``turnstile_replay.replay``
hands the variant to the backend, and BOTH backends (``MockBackend`` and the
paid ``OpenAIBackend``) read ONLY ``variant.model_routing``.

``REPRICING_VARIANTS`` (Section A of docs/superpowers/GLM-OVERNIGHT-BATCH.md)
are remedies with a deterministic transform (``transforms.REPRICING_TRANSFORMS``),
executed by ``run_repricing_matrix``: no backend, no spend, per-trace
delta = re-priced(transformed) - original. Their savings are CONDITIONAL --
the transform reduces/re-rates work, so preservation of the outcome is
unverified on the synthetic corpus (H-1) -- and every consumer must label
them ``repricing.CONDITIONAL_SAVINGS_LABEL`` and keep them OUT of gated
``proven_savings`` (``margin.recoverable_margin(conditional=...)`` puts them
in the separate conditional bucket). They are deliberately NOT in
``VARIANTS``: the backend does not read their fields, so running them there
would replay as the zero-delta no-op ``guard.assert_backend_executable``
refuses.

``RESERVED_VARIANTS`` are honestly-specified specs with NO execution path
yet; they mirror detector ``proposed_variant`` remedies still awaiting their
deterministic transform. After Section A the dict is EMPTY: every token/cost
path remedy now executes. The ``tts_chunking`` FIELD remains reserved
(guard.RESERVED_VARIANT_FIELDS) -- D6/D7 belong to the barge-in acoustic
track, deliberately out of the deterministic cost path's scope.

They are deliberately NOT in ``VARIANTS`` or ``REPRICING_VARIANTS``: running
one would be a zero-delta no-op that looks measured but proves nothing, and
on ``--paid`` it would spend real credit doing so.
``turnstile_experiments.guard`` enforces that -- passing a reserved variant
to the runner raises ``NotImplementedError`` at experiment start. (An
earlier version ran six as the "matrix" and the first paid smoke burned
~5/6 of its spend on identical calls; this split is the fix.)
"""
from __future__ import annotations

from turnstile_schema import VariantSpec

# Executable matrix -- the variants the replay backend actually applies.
VARIANTS: dict[str, VariantSpec] = {
    "model_routing_gpt5_nano": VariantSpec(model_routing={"route": "gpt-5-nano"}),
}

# Re-pricing-executable -- deterministic transform exists (Section A); run
# via run_repricing_matrix, NEVER via the backend. Savings are conditional
# (preservation unverified, Wave-2) and reported in the separate conditional
# bucket, never in gated proven_savings.
REPRICING_VARIANTS: dict[str, VariantSpec] = {
    "context_window_8": VariantSpec(context_strategy="window:8"),
    "context_summarize_2000": VariantSpec(context_strategy="summarize:2000"),
    "prefix_caching_on": VariantSpec(prefix_caching=True),
    "tool_batching_on": VariantSpec(tool_batching=True),
    "escalation_threshold_0_85": VariantSpec(escalation_policy="threshold:0.85"),
    "retrieval_threshold_0_8": VariantSpec(retrieval_policy="threshold:0.8"),
}

# Reserved -- valid remedies with NO execution path yet (see module
# docstring). Now EMPTY at the variant level: every token/cost-path remedy
# has a deterministic transform. ``tts_chunking`` stays reserved at the FIELD
# level (guard.RESERVED_VARIANT_FIELDS) on purpose -- it interacts with the
# barge-in acoustic track, not the deterministic cost path (batch doc:
# "Skip tts_chunking here").
RESERVED_VARIANTS: dict[str, VariantSpec] = {}
