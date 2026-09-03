import sys
from pathlib import Path

# build_data.py is a script (not an installed package); put its directory on
# sys.path so tests can import it like test_run_cli.py loads its CLI.
DASHBOARD = Path(__file__).resolve().parents[1]
if str(DASHBOARD) not in sys.path:
    sys.path.insert(0, str(DASHBOARD))
