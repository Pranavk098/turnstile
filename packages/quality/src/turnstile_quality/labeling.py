"""Hand-labeling records for Day-4 judge calibration (Part A).

One JSONL line per (call, dimension) labeling event. The two writer roles
are deliberately split:

* ``reference_*`` is the pre-label from the paid reference labeler
  (Part E, lives in ``scripts/`` per the no-network rule). It carries a
  label AND a confidence in [0, 1] because Part B needs the confidence
  for ECE.
* ``human_*`` is the rater's verdict, entered through the
  ``python -m turnstile_quality label`` CLI in ``__main__.py``.

Cohen's kappa is computed reference-vs-human over human-checked rows
(Part B). A row with ``human_label=None`` is *unchecked* and MUST NOT
count toward n -- see :func:`checked_pairs` and :func:`count_checked`,
which both filter on ``human_label is not None``.

No network imports (the ``test_no_network_imports_in_quality_package``
gate bans them in this package): only stdlib, pydantic, and the local
calibration constants.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from turnstile_quality.calibration import JUDGE_DIMENSIONS

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")

LabelValue = Literal["pass", "fail"]

#: Committed selection manifest (repo-relative). The CLI ``selection
#: --rebuild`` subcommand regenerates this file byte-identically.
SELECTION_PATH = Path("fixtures/calibration/selection.json")

#: Seed recorded in the manifest. Selection is fully deterministic
#: (sorted ids, fixed rule), so the seed is provenance, not randomness.
SELECTION_SEED = 4

#: The rule, stated once here and echoed into the manifest. Golden
#: fixtures first (sorted by filename), then native-sample calls from
#: ``packages/ingest/data/data.json`` (sorted by id), until >= 60.
SELECTION_NOTE = (
    "all golden fixtures (fixtures/golden/*.json, sorted by filename) "
    "+ native-sample calls (packages/ingest/data/data.json calls, sorted "
    "by id, first N to reach 60); conversations sorted by call_id"
)

#: Minimum conversations in a committed selection (gate needs n >= 60
#: human-checked rows per dimension, so the pool must hold at least 60).
MIN_SELECTION_CONVERSATIONS = 60


class LabelRecord(BaseModel):
    """One (call, dimension) labeling event."""

    model_config = _STRICT

    call_id: str = Field(min_length=1)
    dim_id: str
    reference_label: LabelValue | None = None
    reference_confidence: float | None = None
    human_label: LabelValue | None = None
    rater: str | None = None
    checked_at: datetime | None = None
    note: str | None = None

    @field_validator("dim_id")
    @classmethod
    def _known_dimension(cls, value: str) -> str:
        if value not in JUDGE_DIMENSIONS:
            raise ValueError(
                f"unknown judge dimension {value!r} "
                f"(known: {', '.join(JUDGE_DIMENSIONS)})"
            )
        return value

    @field_validator("reference_confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(
                f"reference_confidence must be a finite float in [0, 1], "
                f"got {value!r}"
            )
        return value


def is_checked(record: LabelRecord) -> bool:
    """A row counts toward n only once a human has rendered a verdict."""
    return record.human_label is not None


def checked_pairs(records: list[LabelRecord]) -> set[tuple[str, str]]:
    """(call_id, dim_id) pairs with a human verdict. Unchecked rows
    (human_label=None) are excluded -- they MUST NOT count toward n."""
    return {
        (record.call_id, record.dim_id) for record in records if is_checked(record)
    }


def count_checked(records: list[LabelRecord]) -> dict[str, int]:
    """Human-checked rows per judge dimension (unchecked rows excluded)."""
    counts = {dim_id: 0 for dim_id in JUDGE_DIMENSIONS}
    for record in records:
        if is_checked(record):
            counts[record.dim_id] += 1
    return counts


def reference_for(
    records: list[LabelRecord], call_id: str, dim_id: str
) -> LabelRecord | None:
    """Latest row for (call_id, dim_id) carrying a reference pre-label."""
    found: LabelRecord | None = None
    for record in records:
        if (
            record.call_id == call_id
            and record.dim_id == dim_id
            and record.reference_label is not None
        ):
            found = record
    return found


def read_label_records(path: str | Path) -> list[LabelRecord]:
    """Read a JSONL labels file (missing file -> []; blank lines skipped)."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    records = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(LabelRecord.model_validate_json(line))
    return records


def append_label_record(path: str | Path, record: LabelRecord) -> None:
    """Append one validated row (append-only: history is never rewritten)."""
    file_path = Path(path)
    if file_path.parent != Path("") and str(file_path.parent) not in (".", ""):
        file_path.parent.mkdir(parents=True, exist_ok=True)
    validated = LabelRecord.model_validate(record.model_dump())
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(validated.model_dump_json() + "\n")


def find_repo_root(start: str | Path | None = None) -> Path:
    """Walk up from ``start`` (default: CWD) to the repo root, marked by
    ``fixtures/golden``. Raises ``FileNotFoundError`` when not found."""
    current = Path(start if start is not None else Path.cwd()).resolve()
    for _ in range(12):
        if (current / "fixtures" / "golden").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    raise FileNotFoundError(
        "repo root (fixtures/golden) not found above "
        f"{Path(start) if start is not None else Path.cwd()}"
    )


def resolve_source(source: str, root: str | Path) -> Path:
    """Resolve a manifest ``source`` entry: absolute paths as-is, relative
    paths against the repo root."""
    candidate = Path(source)
    if candidate.is_absolute():
        return candidate
    return Path(root) / candidate


def build_selection(root: str | Path) -> dict:
    """Derive the committed selection deterministically from committed data.

    Rule (see SELECTION_NOTE): every golden fixture sorted by filename,
    then native-sample calls sorted by id, first N to reach >= 60 total.
    Raises ``FileNotFoundError`` if a backing file is missing and
    ``ValueError`` if the pool holds fewer than 60 conversations.
    """
    root = Path(root)
    entries: list[dict[str, str]] = []

    golden_files = sorted((root / "fixtures" / "golden").glob("*.json"))
    for golden in golden_files:
        entries.append(
            {"call_id": golden.stem, "source": golden.relative_to(root).as_posix()}
        )

    data_path = root / "packages" / "ingest" / "data" / "data.json"
    if not data_path.exists():
        raise FileNotFoundError(f"native sample rollup not found: {data_path}")
    calls = json.loads(data_path.read_text(encoding="utf-8"))["calls"]
    native = sorted(calls, key=lambda call: call["id"])
    needed = max(0, MIN_SELECTION_CONVERSATIONS - len(entries))
    for call in native[:needed]:
        detail = root / "packages" / "ingest" / "data" / call["detail"]
        if not detail.exists():
            raise FileNotFoundError(f"native sample detail not found: {detail}")
        entries.append(
            {
                "call_id": call["id"],
                "source": detail.relative_to(root).as_posix(),
            }
        )

    if len(entries) < MIN_SELECTION_CONVERSATIONS:
        raise ValueError(
            f"selection pool too small: {len(entries)} conversations "
            f"(need >= {MIN_SELECTION_CONVERSATIONS})"
        )
    entries.sort(key=lambda entry: entry["call_id"])
    return {
        "seed": SELECTION_SEED,
        "selection_note": SELECTION_NOTE,
        "conversations": entries,
    }


def render_selection(selection: dict) -> str:
    """Canonical bytes for the manifest (fixed formatting + trailing newline)."""
    return json.dumps(selection, indent=2) + "\n"


def rebuild_selection(selection_path: str | Path, root: str | Path) -> str:
    """Regenerate the manifest from committed data and write it. Returns the
    canonical text (identical bytes when the rule and data are unchanged)."""
    text = render_selection(build_selection(root))
    target = Path(selection_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return text


def load_selection(path: str | Path, root: str | Path) -> dict:
    """Load and validate a selection manifest (unique call_ids, known keys,
    backing files present)."""
    selection = json.loads(Path(path).read_text(encoding="utf-8"))
    conversations = selection.get("conversations", [])
    seen: set[str] = set()
    for entry in conversations:
        if set(entry) != {"call_id", "source"}:
            raise ValueError(f"selection entry must hold call_id + source: {entry!r}")
        if entry["call_id"] in seen:
            raise ValueError(f"duplicate call_id in selection: {entry['call_id']!r}")
        seen.add(entry["call_id"])
        if not resolve_source(entry["source"], root).exists():
            raise FileNotFoundError(
                f"selection source missing: {entry['source']!r}"
            )
    return selection


def load_source_document(source: str, root: str | Path) -> dict:
    """Load a conversation source file (golden trace or wrapped call)."""
    return json.loads(resolve_source(source, root).read_text(encoding="utf-8"))


def _first_text(spans: list, keys: tuple[str, ...]) -> str | None:
    for span in spans:
        if not isinstance(span, dict):
            continue
        for key in keys:
            value = span.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


_CALLER_KEYS = ("transcript", "turnstile.transcript")
_AGENT_KEYS = (
    "output_text",
    "turnstile.output_text",
    "text",
    "turnstile.text",
)


def render_transcript(document: dict) -> list[str]:
    """Caller/agent text per turn, tolerant of both source shapes: golden
    v1.1 traces (dotted ``turnstile.*`` keys, often caller-silent) and
    adapter-shaped calls (``transcript`` / ``output_text``). Wrapped call
    files (``{"trace": {...}}``) are unwrapped automatically."""
    trace = document.get("trace", document)
    if not isinstance(trace, dict):
        return ["(unrecognized source shape: no trace object)"]
    turns = trace.get("turns", [])
    lines: list[str] = []
    for turn in turns:
        index = turn.get("turn_index", "?")
        caller = _first_text(turn.get("asr", []), _CALLER_KEYS)
        agent = _first_text(turn.get("llm", []), _AGENT_KEYS)
        if agent is None:
            agent = _first_text(turn.get("tts", []), _AGENT_KEYS)
        if caller is not None:
            lines.append(f"T{index} caller: {caller}")
        if agent is not None:
            lines.append(f"T{index} agent: {agent}")
        if caller is None and agent is None:
            lines.append(f"T{index} (no text in this turn)")
    if not lines:
        lines.append("(no turns in this conversation)")
    return lines


__all__ = [
    "JUDGE_DIMENSIONS",
    "LabelRecord",
    "LabelValue",
    "MIN_SELECTION_CONVERSATIONS",
    "SELECTION_NOTE",
    "SELECTION_PATH",
    "SELECTION_SEED",
    "append_label_record",
    "build_selection",
    "checked_pairs",
    "count_checked",
    "find_repo_root",
    "is_checked",
    "load_selection",
    "load_source_document",
    "read_label_records",
    "rebuild_selection",
    "reference_for",
    "render_selection",
    "render_transcript",
    "resolve_source",
]
