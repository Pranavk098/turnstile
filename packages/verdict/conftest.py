"""Make turnstile_verdict importable when running `pytest packages/verdict`
without installing the package (turnstile-schema is already provided editable by
the workspace dev group; this only wires up this package's own src/)."""
import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
