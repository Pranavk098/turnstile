"""Tests for the run_experiments.py CLI's paid-run runability (H-2) and
pre-spend path validation (M-1).

The CLI module is loaded by file path (it is a script, not an installed
package). Nothing here reaches the network: the OpenAIBackend class the CLI
would construct is monkeypatched with a MockBackend-derived recorder before
main() runs, and TURNSTILE_ALLOW_PAID / OPENAI_API_KEY are inert test values.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from turnstile_replay import MockBackend

_CLI = Path(__file__).resolve().parents[1] / "run_experiments.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("turnstile_run_experiments_cli", _CLI)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _RecordingBackend(MockBackend):
    """MockBackend behavior, but records construction -- proves the CLI got
    this far (and that nothing needed stdin to do it)."""
    constructed = 0

    def __init__(self, *args, **kwargs):
        type(self).constructed += 1
        super().__init__()


@pytest.fixture(autouse=True)
def _reset_recorder():
    _RecordingBackend.constructed = 0
    yield
    _RecordingBackend.constructed = 0


# --------------------------------------------------------------------------- #
# H-2: --paid --yes runs non-interactively (no stdin), env gate still applied. #
# --------------------------------------------------------------------------- #

def test_paid_yes_constructs_backend_without_stdin(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setattr(
        "turnstile_experiments.OpenAIBackend", _RecordingBackend)

    def _no_stdin(*args, **kwargs):
        raise AssertionError("input() called -- --yes did not skip the prompt")

    monkeypatch.setattr("builtins.input", _no_stdin)

    cli = _load_cli()
    out = tmp_path / "results.json"
    cli.main([
        "--n", "2", "--seed", "0",
        "--paid", "--yes",
        "--out", str(out),
        "--checkpoint", str(tmp_path / "ck.jsonl"),
    ])

    assert _RecordingBackend.constructed == 1
    assert out.exists()  # the run completed and wrote results
    assert "--yes given" in capsys.readouterr().out


def test_paid_without_yes_still_requires_interactive_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setattr("turnstile_experiments.OpenAIBackend", _RecordingBackend)

    calls = []

    def _stdin_says_no(prompt):
        calls.append(prompt)
        return "no"

    monkeypatch.setattr("builtins.input", _stdin_says_no)

    cli = _load_cli()
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--n", "2", "--seed", "0", "--paid",
            "--out", str(tmp_path / "results.json"),
        ])
    assert exc.value.code == 1
    assert len(calls) == 1  # the estimate prompt WAS shown...
    assert _RecordingBackend.constructed == 0  # ...and refused, no backend


def test_paid_yes_env_gate_still_required(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TURNSTILE_ALLOW_PAID", raising=False)
    monkeypatch.setattr("turnstile_experiments.OpenAIBackend", _RecordingBackend)

    cli = _load_cli()
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--n", "2", "--seed", "0", "--paid", "--yes",
            "--out", str(tmp_path / "results.json"),
        ])
    assert exc.value.code == 1
    assert _RecordingBackend.constructed == 0
    assert "TURNSTILE_ALLOW_PAID" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# M-1: unwritable output paths abort BEFORE any backend construction.         #
# --------------------------------------------------------------------------- #

def test_unwritable_out_aborts_before_backend_construction(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setattr("turnstile_experiments.OpenAIBackend", _RecordingBackend)
    monkeypatch.setattr(
        "builtins.input",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("input() reached")),
    )

    blocker = tmp_path / "blocker.txt"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    cli = _load_cli()
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--n", "2", "--seed", "0", "--paid", "--yes",
            "--out", str(blocker / "results.json"),  # parent is a FILE
        ])
    assert exc.value.code == 1
    assert _RecordingBackend.constructed == 0
    assert "not writable" in capsys.readouterr().out


def test_unwritable_checkpoint_aborts_before_backend_construction(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setattr("turnstile_experiments.OpenAIBackend", _RecordingBackend)

    blocker = tmp_path / "blocker.txt"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    cli = _load_cli()
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "--n", "2", "--seed", "0", "--paid", "--yes",
            "--out", str(tmp_path / "results.json"),           # writable
            "--checkpoint", str(blocker / "ck.jsonl"),          # NOT writable
        ])
    assert exc.value.code == 1
    assert _RecordingBackend.constructed == 0
    assert "not writable" in capsys.readouterr().out


def test_probe_does_not_truncate_existing_results(monkeypatch, tmp_path):
    """The M-1 probe opens for append: if the run later dies before writing,
    a prior run's results file must be intact. Observed by failing the run
    right AFTER the probe (corpus generation) and checking the file."""
    monkeypatch.setenv("TURNSTILE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setattr("turnstile_experiments.OpenAIBackend", _RecordingBackend)

    existing = tmp_path / "results.json"
    existing.write_text("PRIOR RUN CONTENTS", encoding="utf-8")
    cli = _load_cli()

    def _boom(n, seed):
        raise RuntimeError("die after the probe, before any results write")

    monkeypatch.setattr(cli, "generate_corpus", _boom)
    with pytest.raises(RuntimeError):
        cli.main([
            "--n", "2", "--seed", "0",
            "--out", str(existing),
            "--checkpoint", str(tmp_path / "ck.jsonl"),
        ])
    assert existing.read_text(encoding="utf-8") == "PRIOR RUN CONTENTS"
