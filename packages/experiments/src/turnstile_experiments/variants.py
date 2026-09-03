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

``HARNESS_VARIANTS`` (batch 2, T1) is the last remedy lever: ``tts_chunking``
-- D6/D7's proposed remedy -- now has a MEASURED execution path on the
barge-in harness (``turnstile_agent`` synthesis granularity knob, driven by
``run_bargein_report``'s granularity sweep). Each granularity re-synthesizes
every readback through real Piper, so its numbers are MEASURED harness
results with bootstrap CIs -- reported in the barge-in report, in NEITHER
the conditional re-pricing bucket (there is no deterministic trace transform
for it) NOR the gated backend bucket (the replay backend does not read the
field). ``guard.assert_backend_executable`` refuses it on the backend path
like the re-pricing fields.

``RESERVED_VARIANTS`` are honestly-specified specs with NO execution path
yet. It is now EMPTY at both levels: every VariantSpec field executes
somewhere (backend / re-pricing / harness). The empty dict is kept as the
place reserved-but-unexecuted remedies would land.

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

# Harness-executed -- the tts_chunking remedy (D6/D7): a MEASURED path on the
# barge-in harness (real Piper synthesis at each granularity), NOT a
# deterministic trace transform. Savings are measured harness results with
# CIs, reported in the barge-in report -- in neither the conditional bucket
# nor gated proven_savings. Never passed to the backend.
HARNESS_VARIANTS: dict[str, VariantSpec] = {
    "tts_chunking_sentence": VariantSpec(tts_chunking="sentence"),
    "tts_chunking_clause": VariantSpec(tts_chunking="clause"),
    "tts_chunking_word": VariantSpec(tts_chunking="word"),
}

# Reserved -- valid remedies with NO execution path yet. EMPTY since batch 2
# T1: every VariantSpec field now executes (backend / re-pricing / harness).
RESERVED_VARIANTS: dict[str, VariantSpec] = {}
