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
yet. Each mirrors a detector's ``proposed_variant`` remedy, so they are kept
here as the concrete to-do list for promoting those findings from Tier-2
(detected + quantified) to executable:

  * retrieval_policy                -> D3 (redundant retrieval)
  * tts_chunking                    -> D6 (dead tokens), D7 (barge-in)

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
    "prefix_caching_on": VariantSpec(prefix_caching=True),
    "tool_batching_on": VariantSpec(tool_batching=True),
    "escalation_threshold_0_85": VariantSpec(escalation_policy="threshold:0.85"),
}

# Reserved -- valid remedies with NO execution path yet (see module
# docstring). Documented, NOT run by any runner.
RESERVED_VARIANTS: dict[str, VariantSpec] = {
    "retrieval_threshold_0_8": VariantSpec(retrieval_policy="threshold:0.8"),
    "tts_chunking_sentence": VariantSpec(tts_chunking="sentence"),
}
