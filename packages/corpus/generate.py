#!/usr/bin/env python
"""CLI entry point: uv run python packages/corpus/generate.py --n 250 --seed <int> --out corpus/

Thin shim over turnstile_corpus.generate (src/turnstile_corpus/generate.py) --
wires this package's src/ onto sys.path (same fallback packages/pricing/
conftest.py uses for pytest) so the script runs standalone even without a
prior `uv sync`, then delegates to the real implementation.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from turnstile_corpus.generate import main  # noqa: E402 -- after the sys.path shim above

if __name__ == "__main__":
    main()
