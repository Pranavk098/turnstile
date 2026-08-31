"""Make turnstile_detectors importable when running `pytest packages/detectors`
without installing the package (turnstile-schema is already provided editable by
the workspace dev group; this wires up this package's own src/). Tests also need
turnstile_pricing (to build realistic PricedTrace fixtures with real costs) and
turnstile_verdict (test_fixture_sweep.py adjudicates real Verdicts for the full
10-class sweep -- Detector 9 reads verdict.label/turn_of_no_return, so a dummy
always-RESOLVED verdict would leave it permanently silent). Neither is a runtime
dependency of turnstile_detectors itself (detect() consumes an already-priced
trace and an already-adjudicated verdict), so neither is declared in
pyproject.toml; both src/ dirs are exposed here the same way, per the package
brief."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _pkg in ("detectors", "pricing", "verdict"):
    _src = _ROOT.parent / _pkg / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
