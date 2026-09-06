"""Make turnstile_ingest importable when running `pytest packages/ingest`
without installing the package (turnstile-schema and the pipeline packages
are already provided editable by the workspace dev group; this wires up this
package's own src/). Mirrors packages/detectors/conftest.py."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _pkg in ("ingest", "pricing", "verdict", "detectors", "replay", "stats"):
    _src = _ROOT.parent / _pkg / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
