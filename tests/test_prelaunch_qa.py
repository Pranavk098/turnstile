"""Day-7 QA-gate tests: math helpers + seeded-failure abort (no network needed).

The abort tests run the real gate against a dead localhost port (connection
refused is instant) -- they never touch LIVE and need no secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prelaunch_qa import _p95_ms, main  # noqa: E402


def test_p95_single_sample_is_itself():
    assert _p95_ms([3.0]) == 3.0


def test_p95_marks_the_tail():
    assert _p95_ms([1.0] * 19 + [100.0]) > 50.0


def test_seeded_failure_aborts_with_gate_named(capsys):
    assert main(["--self-test"]) == 0
    assert "ABORT gate=demo-up" in capsys.readouterr().out


def test_dead_base_exits_nonzero_naming_demo_up(capsys):
    assert main(["--base", "http://127.0.0.1:1"]) == 2
    assert "FAIL demo-up" in capsys.readouterr().out
