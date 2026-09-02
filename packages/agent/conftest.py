"""Make turnstile_agent importable when running `pytest packages/agent`
without relying on workspace install state (mirrors the other packages'
conftest shims; turnstile-agent IS a workspace member, this is belt-and-
braces for direct package-scoped runs)."""
import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
