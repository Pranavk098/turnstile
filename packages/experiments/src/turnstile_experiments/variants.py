"""The six PRD Sec.8.2 replay variants -- one knob isolated per variant, so
each experiment measures a single lever cleanly.

``turnstile_replay``'s Wave-1 ``MockBackend`` differentiates behavior on
``model_routing`` only (see ``turnstile_replay.backend``'s docstring); the
other five variants below are real, honestly-specified ``VariantSpec``s that
mostly produce ``excluded``/identity (no-op) trials against ``MockBackend``
this wave -- there is no live backend yet to change behavior on
``context_strategy``/``prefix_caching``/``retrieval_policy``/
``tts_chunking``/``escalation_policy``. That is documented here and in the
experiments report, not hidden: running the matrix honestly, even when most
of it is a no-op under the free backend, is the point -- a real backend
(``turnstile_experiments.OpenAIBackend``) fills these in later.
"""
from __future__ import annotations

from turnstile_schema import VariantSpec

VARIANTS: dict[str, VariantSpec] = {
    "model_routing_gpt5_nano": VariantSpec(model_routing={"route": "gpt-5-nano"}),
    "context_window_8": VariantSpec(context_strategy="window:8"),
    "prefix_caching_on": VariantSpec(prefix_caching=True),
    "retrieval_threshold_0_8": VariantSpec(retrieval_policy="threshold:0.8"),
    "tts_chunking_sentence": VariantSpec(tts_chunking="sentence"),
    "escalation_threshold_0_85": VariantSpec(escalation_policy="threshold:0.85"),
}
