"""Link check over the README, root docs, docs/, and dashboard HTML.

Fails on broken LOCAL links (missing files, missing #anchors); EXTERNAL
http(s) links are reported, never failed -- CI must not flake on someone
else's uptime. Run: ``uv run python scripts/check_links.py``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MD_FILES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md", ROOT / "CODE_OF_CONDUCT.md",
            *sorted((ROOT / "docs").rglob("*.md"))]
HTML_FILES = sorted((ROOT / "packages" / "dashboard").glob("*.html"))

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_LINK_RE = re.compile(r"(?:href|src)=\"([^\"]+)\"")


def github_slug(header: str) -> str:
    slug = header.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"\s+", "-", slug)


def md_anchors(path: Path) -> set[str]:
    anchors = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"#{1,6}\s+(.*)", line)
        if match:
            anchors.add(github_slug(match.group(1)))
    return anchors


def html_ids(path: Path) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', path.read_text(encoding="utf-8")))


def check() -> int:
    broken: list[str] = []
    external: list[str] = []

    def check_target(source: Path, target: str) -> None:
        if target.startswith(("http://", "https://", "mailto:")):
            external.append(f"{source.name}: {target}")
            return
        if target.startswith("#"):
            anchors = (md_anchors(source) if source.suffix == ".md"
                       else html_ids(source))
            if target[1:] not in anchors:
                broken.append(f"{source}: anchor {target} not found")
            return
        file_part, _, anchor = target.partition("#")
        resolved = (source.parent / file_part).resolve()
        if not resolved.exists():
            broken.append(f"{source}: {target} -> missing {resolved}")
            return
        if anchor and resolved.suffix in (".md", ".html"):
            anchors = (md_anchors(resolved) if resolved.suffix == ".md"
                       else html_ids(resolved))
            if anchor not in anchors:
                broken.append(f"{source}: {target} -> anchor #{anchor} not found")

    for path in MD_FILES:
        if not path.exists():
            broken.append(f"expected doc missing: {path}")
            continue
        for target in MD_LINK_RE.findall(path.read_text(encoding="utf-8")):
            check_target(path, target)

    for path in HTML_FILES:
        for target in HTML_LINK_RE.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("#/", "data:")):
                continue  # JS hash routes, not files
            check_target(path, target)

    for ext in sorted(set(external)):
        print(f"external (unchecked): {ext}")
    if broken:
        print("BROKEN LINKS:")
        for line in broken:
            print(f"  {line}")
        return 1
    print(f"link check green ({len(MD_FILES)} md + {len(HTML_FILES)} html files)")
    return 0


if __name__ == "__main__":
    sys.exit(check())
