"""Rate loading for replay's internal re-pricing step.

`replay()`'s signature (PRD Sec.5) carries no rates parameter -- same problem
`packages/detectors/_rates.py` solves, same fix: load `pricing/rates.yaml`
directly. This is the SAME file `packages/pricing.price_trace()` prices the
original trace against, so a replayed trace's (possibly rerouted) model
always resolves against the same rate table the original conv_cost was
computed from.
"""
from __future__ import annotations

from functools import lru_cache

from turnstile_schema import RateTable, load_rates

# Relative to the process CWD, matching every other invocation in this repo
# (Makefile, other packages' _rates.py) which always runs `uv run pytest ...`
# from the repository root.
RATES_PATH = "pricing/rates.yaml"


@lru_cache(maxsize=1)
def get_rates() -> RateTable:
    return load_rates(RATES_PATH)
