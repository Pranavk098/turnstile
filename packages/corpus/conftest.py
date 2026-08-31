"""Make turnstile_corpus importable when running `pytest packages/corpus`
without installing the package (turnstile-schema is already provided editable by
the workspace dev group). Tests also exercise the pipeline end-to-end
(price_trace / adjudicate on generated traces, PRD Sec.5), so this wires up
turnstile_pricing and turnstile_verdict's src/ too, the same cross-package
pattern packages/detectors/conftest.py uses. Neither is a runtime dependency
of turnstile_corpus itself (generate.py only depends on turnstile_schema +
numpy -- see pyproject.toml), so neither is declared there."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
for _pkg in ("corpus", "pricing", "verdict"):
    _src = _ROOT.parent / _pkg / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
