"""Make turnstile_detectors importable when running `pytest packages/detectors`
without installing the package (turnstile-schema is already provided editable by
the workspace dev group; this wires up this package's own src/). Tests also need
turnstile_pricing (to build realistic PricedTrace fixtures with real costs) --
that is not a runtime dependency of turnstile_detectors itself (detect() consumes
an already-priced trace), so it is not declared in pyproject.toml; its src/ is
exposed here the same way, per the package brief."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _pkg in ("detectors", "pricing"):
    _src = _ROOT.parent / _pkg / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
