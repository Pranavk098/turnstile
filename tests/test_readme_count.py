"""README suite-count guard (06 improvement): the stated count can't rot.

Parses `N passed, M skipped` from README.md and asserts it matches a real
full-suite run (subprocess, so the counting run is the same suite the badge
reflects). Counts come from `--junitxml` (machine-readable) rather than the
terminal summary. Recursion-guarded via env: the inner run skips this file.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD_ENV = "TURNSTILE_README_GUARD_ACTIVE"
COUNT_RE = re.compile(r"(\d+) passed, (\d+) skipped")


def _readme_counts() -> tuple[int, int]:
    match = COUNT_RE.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert match, "README states no 'N passed, M skipped' count to guard"
    return int(match.group(1)), int(match.group(2))


def test_readme_suite_count_matches():
    if os.environ.get(GUARD_ENV):
        pytest.skip("recursion guard: the counting run does not count itself")
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = str(Path(tmp) / "results.xml")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q",
             f"--junitxml={xml_path}"],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
            env={**os.environ, GUARD_ENV: "1"},
        )
        assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
        suite = ET.parse(xml_path).getroot().find("testsuite")
        assert suite is not None, "junitxml has no testsuite element"
        tests = int(suite.get("tests", 0))
        skipped = int(suite.get("skipped", 0))
        failures = int(suite.get("failures", 0))
        errors = int(suite.get("errors", 0))
    assert (failures, errors) == (0, 0)
    observed = (tests - skipped - failures - errors, skipped)
    # The counting run skips this very test, so it observes one fewer pass
    # and one more skip than a full green run the README describes.
    expected = _readme_counts()
    assert observed == (expected[0] - 1, expected[1] + 1), (
        f"suite ran {observed[0] + 1} passed, {observed[1] - 1} skipped but README "
        f"says {expected} -- update the README count"
    )
