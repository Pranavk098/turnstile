"""Doc-number guard (Day-6 P1-4): key figures in README/(docs/index) MUST stay
== their source docs, or CI fails.

Sources of truth: docs/METHOD.md (recoverable margin, barge-in waste),
PERF.md (speedup, cache-hit, cold eval). Pytest counts are checked against a
real `--collect-only` run (fast); the full-suite pin lives in-suite at
tests/test_readme_count.py, which this job complements, not duplicates.

Run: ``uv run python scripts/check_doc_numbers.py [--root PATH]``.
Exit 0 = all figures match; exit 1 = divergence (message names the figure,
the display file, and the source file).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
DEFAULT_ROOT = HERE.parents[1]

# (name, topic regex, display literal, source file, source literal)
# Topic regexes are whole-word so a passing mention ("speedups page") does
# not engage the guard -- only a passage actually stating the figure does.
FIGURE_CHECKS: tuple[tuple[str, str, str, str, str], ...] = (
    ("recoverable margin", r"recoverable margin", "0.57%",
     "docs/METHOD.md", "0.57% [0.49, 0.66]"),
    ("barge-in waste", r"barge-in", "~4%",
     "docs/METHOD.md", "~4%"),
    ("matrix speedup", r"\bspeedup\b", "4.46\u00d7",
     "PERF.md", "4.46\u00d7"),
    ("cache-hit eval", r"cache-hit", "1.4 ms",
     "PERF.md", "1.4 ms"),
    ("cold eval", r"cold eval", "66.1 ms",
     "PERF.md", "66.1 ms"),
)

# docs/index.md is the mkdocs landing page (another Day-6 track owns it).
# Guarded IF present, skipped if not -- never fail on another track's scope.
OPTIONAL_DISPLAY_FILES = ("docs/index.md",)

COUNT_RE = re.compile(r"(\d+) passed, (\d+) skipped")
PER_FILE_RE = re.compile(r": (\d+)\s*$")


def check_figures(root: Path) -> list[str]:
    failures: list[str] = []
    # README.md states every figure, so it is always fully checked. Optional
    # display files (e.g. the mkdocs landing page, which deliberately repeats
    # no numbers) are checked per-topic: a figure is enforced there only when
    # the file discusses that topic -- divergence, not repetition, is the
    # failure mode.
    display_required = ["README.md"]
    display_optional = [f for f in OPTIONAL_DISPLAY_FILES
                        if (root / f).exists()]
    for name, topic, disp_lit, src, src_lit in FIGURE_CHECKS:
        for d in display_required:
            text = (root / d).read_text(encoding="utf-8")
            if disp_lit not in text:
                failures.append(
                    f"{name}: {d} lacks {disp_lit!r} "
                    f"(source: {src} pins {src_lit!r})")
        for d in display_optional:
            text = (root / d).read_text(encoding="utf-8")
            if re.search(topic, text, re.IGNORECASE) and disp_lit not in text:
                failures.append(
                    f"{name}: {d} discusses {topic!r} but states "
                    f"{disp_lit!r} differently "
                    f"(source: {src} pins {src_lit!r})")
        src_text = (root / src).read_text(encoding="utf-8")
        if src_lit not in src_text:
            failures.append(
                f"{name}: SOURCE DRIFT -- {src} no longer pins {src_lit!r}")
    return failures


def check_pytest_count(root: Path) -> list[str]:
    """README's 'N passed, M skipped' MUST sum to a real collection total."""
    readme = (root / "README.md").read_text(encoding="utf-8")
    match = COUNT_RE.search(readme)
    if not match:
        return ["pytest count: README states no 'N passed, M skipped' count"]
    claimed = int(match.group(1)) + int(match.group(2))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        return ["pytest count: collection failed:\n"
                + (proc.stdout + proc.stderr)[-1500:]]
    total = sum(int(m.group(1)) for line in proc.stdout.splitlines()
                if (m := PER_FILE_RE.search(line.strip())))
    if total != claimed:
        return [f"pytest count: README claims {match.group(0)} "
                f"(={claimed}) but collection finds {total} tests "
                f"-- update the README count"]
    print(f"pytest count green: README '{match.group(0)}' == {total} collected")
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help="doc tree to check (default: repo root)")
    args = parser.parse_args()
    root = Path(args.root)
    failures = check_figures(root) + check_pytest_count(root)
    if failures:
        print("DOC-NUMBER GUARD FAILED:")
        for line in failures:
            print(f"  {line}")
        return 1
    print(f"doc-number guard green "
          f"({len(FIGURE_CHECKS)} figures + pytest count)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
