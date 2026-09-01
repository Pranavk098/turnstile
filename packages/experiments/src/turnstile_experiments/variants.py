"""The replay variant space (PRD Sec.8.2), split by what the replay engine can
actually execute today.

``VARIANTS`` is the EXECUTABLE matrix -- variants the replay path applies for
real, so their trials are genuine measurements. Today that is exactly the
``model_routing`` lever: ``turnstile_replay.replay`` hands the variant to the
backend, and BOTH backends (``MockBackend`` and the paid ``OpenAIBackend``)
read ONLY ``variant.model_routing``.

``RESERVED_VARIANTS`` are honestly-specified specs whose knob the replay engine
does NOT apply yet (``context_strategy``/``prefix_caching``/
``retrieval_policy``/``tts_chunking``/``escalation_policy``/``tool_batching``).
Each mirrors a detector's ``proposed_variant`` remedy, so they are kept here as
the concrete to-do list for promoting those findings from Tier-2 (detected +
quantified) to Tier-1 (replay-proven):

  * context_strategy / prefix_caching -> D2 (context bloat), D4 (turn inflation)
  * retrieval_policy                  -> D3 (redundant retrieval)
  * tts_chunking                      -> D6 (dead tokens), D7 (barge-in)
  * escalation_policy                 -> D9 (escalation debt)
  * tool_batching                     -> D10 (tool thrash)

They are deliberately NOT in ``VARIANTS``: running one would replay as a
zero-delta no-op that looks measured but proves nothing, and on ``--paid`` it
would spend real credit doing so. ``turnstile_experiments.guard`` enforces
that -- passing a reserved variant to the runner raises ``NotImplementedError``
at experiment start. (An earlier version ran all six as the "matrix" and the
first paid smoke burned ~5/6 of its spend on these identical calls; this split
is the fix.)
"""
from __future__ import annotations

from turnstile_schema import VariantSpec

# Executable matrix -- the variants the replay engine actually applies.
VARIANTS: dict[str, VariantSpec] = {
    "model_routing_gpt5_nano": VariantSpec(model_routing={"route": "gpt-5-nano"}),
}

# Reserved -- valid remedies the replay path can't execute yet (see module
# docstring). Documented, NOT run by the matrix.
RESERVED_VARIANTS: dict[str, VariantSpec] = {
    "context_window_8": VariantSpec(context_strategy="window:8"),
    "prefix_caching_on": VariantSpec(prefix_caching=True),
    "retrieval_threshold_0_8": VariantSpec(retrieval_policy="threshold:0.8"),
    "tts_chunking_sentence": VariantSpec(tts_chunking="sentence"),
    "escalation_threshold_0_85": VariantSpec(escalation_policy="threshold:0.85"),
}
