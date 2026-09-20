#!/bin/sh
# Day-5 Part A clean-venv harness: install each of the 7 shippable libraries
# from prebuilt wheels into its own temp venv (no --system-site-packages, no
# uv, repo NOT on sys.path) and run its smoke entry point. Fail-fast, naming
# the package. Spec: docs/prd/sprint-01/day-5-work-split.md §3.
#
# Usage (from anywhere; paths resolve via $0):
#   uv build --package turnstile-schema --out dist/   # ... x7
#   sh scripts/smoke_clean_venv.sh
#
# Env overrides (defaults suit CI; none required):
#   PYTHON_BIN  interpreter used to create the venvs (default: python3, must be >=3.12)
#   DIST        artifact dir relative to the repo root (default: dist)
set -eu

PYTHON_BIN="${PYTHON_BIN:-python3}"
DIST="${DIST:-dist}"
# Install order follows the dependency DAG (a package only after the siblings
# it needs): ingest depends on quality, so quality comes first.
PKGS="schema pricing verdict detectors replay quality ingest"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT/$DIST"

fail() { echo "SMOKE-FAIL: $1" >&2; exit 1; }

unset PYTHONPATH
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "interpreter '$PYTHON_BIN' not found (set PYTHON_BIN to a Python >=3.12)"
"$PYTHON_BIN" --version
[ -d "$DIST_DIR" ] || fail "artifact dir '$DIST_DIR' missing -- build wheels first: uv build --out dist/"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM

for pkg in $PKGS; do
  echo "=== turnstile-$pkg ==="
  wheel=""
  for w in "$DIST_DIR"/turnstile_"$pkg"-*.whl; do
    if [ -e "$w" ]; then wheel="$w"; break; fi
  done
  [ -n "$wheel" ] || fail "turnstile-$pkg: no wheel in $DIST_DIR (expected turnstile_$pkg-*.whl)"
  venv="$WORK/venv-$pkg"
  "$PYTHON_BIN" -m venv "$venv" || fail "turnstile-$pkg: venv creation failed"
  if [ -x "$venv/Scripts/python.exe" ]; then
    VPY="$venv/Scripts/python.exe"
    SMOKE="$venv/Scripts/turnstile-$pkg-smoke.exe"
  else
    VPY="$venv/bin/python"
    SMOKE="$venv/bin/turnstile-$pkg-smoke"
  fi
  "$VPY" -m pip install --disable-pip-version-check --find-links "$DIST_DIR" "turnstile-$pkg" \
    || fail "turnstile-$pkg: pip install failed"
  # Neutral cwd + PYTHONPATH unset (top): the repo must not be importable.
  ( cd "$WORK" && MOD="turnstile_$pkg" VENV="$venv" "$VPY" -c \
    "import importlib, os; m = importlib.import_module(os.environ['MOD']); f = os.path.realpath(m.__file__); assert f.startswith(os.path.realpath(os.environ['VENV'])), f" ) \
    || fail "turnstile-$pkg: import did not resolve inside the clean venv"
  [ -x "$SMOKE" ] || fail "turnstile-$pkg: smoke entry point missing ($SMOKE)"
  start="$(date +%s)"
  out="$(cd "$WORK" && "$SMOKE")" || fail "turnstile-$pkg: smoke exited nonzero"
  end="$(date +%s)"
  case "$out" in
    "ok $pkg "*) ;;
    *) fail "turnstile-$pkg: unexpected smoke output: $out" ;;
  esac
  echo "$out ($((end - start))s)"
done
echo "ALL 7 SMOKES GREEN"
