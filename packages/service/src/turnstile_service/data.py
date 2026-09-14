"""Committed-data access for the demo service.

Every read endpoint serves bytes already committed to the repo -- the
dashboard's ``sample/*.json`` (golden fleet + published ingest copy) and the
ingest CLI's ``packages/ingest/data/data.json``. This module does no pricing,
no detection, no replay: it only locates files and maps ids to filenames.
Engine purity lives here as structure, not just intent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
DASHBOARD_DIR = _REPO_ROOT / "packages" / "dashboard"
SAMPLE_DIR = DASHBOARD_DIR / "sample"
INGEST_DATA_DIR = _REPO_ROOT / "packages" / "ingest" / "data"
INGEST_ARTIFACT = INGEST_DATA_DIR / "data.json"
EXAMPLE_CALL_PATH = Path(__file__).resolve().parent / "example_call.json"

_CALL_ID_RE = re.compile(r"[A-Za-z0-9_-]+\Z")

#: /api/<name> -> committed sample file. The front-end's existing
#: ``sample/*.json`` fetches map 1:1 onto these, so the API is a thin
#: same-origin alias, never a new data source.
READ_ENDPOINTS = {
    "manifest": "manifest.json",
    "fleet": "fleet.json",
    "calls": "calls.json",
    "hero": "priced_trace.json",
    "findings": "findings.sample.json",
    "experiments": "experiments.sample.json",
    "conditional": "conditional.sample.json",
    "bargein": "bargein.sample.json",
}


def read_sample(name: str) -> bytes:
    """Raw bytes of a committed ``sample/`` file (served verbatim)."""
    return (SAMPLE_DIR / name).read_bytes()


def read_ingest_artifact() -> bytes:
    """Raw bytes of the ingest CLI's committed ``data.json`` (verbatim)."""
    return INGEST_ARTIFACT.read_bytes()


def read_example_call() -> bytes:
    """Raw bytes of the ``docs/INGEST.md`` example call (verbatim)."""
    return EXAMPLE_CALL_PATH.read_bytes()


def call_detail_path(call_id: str) -> Path | None:
    """Filesystem path of a prebuilt per-call report, or None.

    ``call_id`` is restricted to the dashboard's route pattern so ids can
    never escape the sample directory (``..``/``/`` rejected, not sanitized).
    """
    if not _CALL_ID_RE.match(call_id):
        return None
    path = SAMPLE_DIR / f"call-{call_id}.json"
    return path if path.exists() else None


def example_call() -> dict:
    """The ``docs/INGEST.md`` example as parsed JSON."""
    return json.loads(EXAMPLE_CALL_PATH.read_text(encoding="utf-8"))
