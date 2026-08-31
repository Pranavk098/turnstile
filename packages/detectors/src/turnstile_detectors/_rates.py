"""Rate loading and rate-key resolution shared by every detector.

`detect()`'s signature (PRD §5) carries no rates parameter, so detectors load
`pricing/rates.yaml` themselves and resolve keys with the SAME convention
`packages/pricing` uses (documented at the top of pricing/rates.yaml and
re-derived independently here, not imported from turnstile_pricing's private
helpers, to keep the two packages' rate-key logic decoupled):

  asr / llm span -> f"{gen_ai.system}/{gen_ai.request.model}"
  tts span       -> gen_ai.system alone
  telephony.leg  -> f"{provider}/pstn_{direction}"
"""
from __future__ import annotations

from functools import lru_cache

from turnstile_schema import RateTable, load_rates
from turnstile_schema.spans import LlmDecide, TelephonyLeg, TtsSynthesize

# Relative to the process CWD, matching every other invocation in this repo
# (Makefile, other packages' docs) which always runs `uv run pytest ...` from
# the repository root.
RATES_PATH = "pricing/rates.yaml"


@lru_cache(maxsize=1)
def get_rates() -> RateTable:
    return load_rates(RATES_PATH)


def llm_key(span: LlmDecide) -> str:
    return f"{span.gen_ai_system}/{span.gen_ai_request_model}"


def tts_key(span: TtsSynthesize) -> str:
    return span.gen_ai_system


def telephony_key(leg: TelephonyLeg) -> str:
    return f"{leg.provider}/pstn_{leg.direction.value}"
