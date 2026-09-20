"""Terminal labeling CLI for Day-4 judge calibration (Part A, $0).

Subcommands (run from the repo root)::

    uv run python -m turnstile_quality label --selection
        fixtures/calibration/selection.json --labels
        fixtures/calibration/labels.jsonl --rater <name>
    uv run python -m turnstile_quality stats --selection ... --labels ...
    uv run python -m turnstile_quality selection --rebuild --selection ...

``label`` walks every unchecked (call, dimension) pair: it prints the
call's transcript, shows the reference pre-label when one exists, and
prompts ``[y] agree / [n] disagree (flip) / [s] skip / [q] quit`` (pairs
with no pre-label prompt ``[p] pass / [f] fail`` instead -- there is
nothing to agree with). Writes are append-only JSONL; a re-run resumes
after the last human-checked row. Every written row is stamped with
``checked_at`` + ``rater``.

``stats`` prints labeled/total per dimension (no scoring math -- kappa
and ECE belong to Part B).

No network imports (package gate): stdlib + pydantic + local modules.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from turnstile_quality.calibration import JUDGE_DIMENSIONS
from turnstile_quality.labeling import (
    LabelRecord,
    append_label_record,
    build_selection,
    checked_pairs,
    count_checked,
    find_repo_root,
    load_selection,
    load_source_document,
    read_label_records,
    reference_for,
    render_selection,
    render_transcript,
)


def _now_iso() -> datetime:
    return datetime.now(timezone.utc)


def _prompt_choice(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def _label_one_pair(
    *,
    call_id: str,
    dim_id: str,
    reference: LabelRecord | None,
    rater: str,
    labels_path: Path,
) -> str:
    """Prompt for one (call, dim) pair; returns 'labeled', 'skipped' or 'quit'."""
    if reference is not None:
        print(f"  [{dim_id}] reference pre-label: {reference.reference_label} "
              f"(confidence {reference.reference_confidence})")
        answer = _prompt_choice("  [y]agree / [n]flip / [s]skip / [q]quit > ")
    else:
        print(f"  [{dim_id}] no reference pre-label for this pair.")
        answer = _prompt_choice("  [p]pass / [f]fail / [s]skip / [q]quit > ")

    human: str | None = None
    if reference is not None:
        if answer in ("y", "yes", "agree"):
            human = reference.reference_label
        elif answer in ("n", "no", "flip", "disagree"):
            if reference.reference_label == "pass":
                human = "fail"
            else:
                human = "pass"
        elif answer in ("s", "skip"):
            print("  skipped.")
            return "skipped"
        elif answer in ("q", "quit"):
            return "quit"
        else:
            print("  unrecognized answer -- skipped.")
            return "skipped"
    else:
        if answer in ("p", "pass"):
            human = "pass"
        elif answer in ("f", "fail"):
            human = "fail"
        elif answer in ("s", "skip"):
            print("  skipped.")
            return "skipped"
        elif answer in ("q", "quit"):
            return "quit"
        else:
            print("  unrecognized answer -- skipped.")
            return "skipped"

    assert human is not None
    append_label_record(
        labels_path,
        LabelRecord(
            call_id=call_id,
            dim_id=dim_id,
            reference_label=reference.reference_label if reference else None,
            reference_confidence=(
                reference.reference_confidence if reference else None
            ),
            human_label=human,  # type: ignore[arg-type]
            rater=rater,
            checked_at=_now_iso(),
        ),
    )
    print(f"  recorded: {dim_id} human={human} (rater {rater}).")
    return "labeled"


def cmd_label(args: argparse.Namespace) -> int:
    rater = args.rater.strip()
    if not rater:
        print("error: --rater must be a non-empty name.", file=sys.stderr)
        return 2
    try:
        root = find_repo_root()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    selection_path = Path(args.selection)
    if not selection_path.exists():
        print(f"error: selection not found: {selection_path}", file=sys.stderr)
        return 2
    try:
        selection = load_selection(selection_path, root)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: bad selection manifest: {exc}", file=sys.stderr)
        return 2

    labels_path = Path(args.labels)
    records = read_label_records(labels_path)
    done = checked_pairs(records)
    counts = count_checked(records)

    conversations = selection.get("conversations", [])
    total_pairs = len(conversations) * len(JUDGE_DIMENSIONS)
    pending = total_pairs - len(done)
    print(f"rater: {rater}")
    print(f"selection: {len(conversations)} conversations x "
          f"{len(JUDGE_DIMENSIONS)} dims = {total_pairs} pairs; "
          f"{len(done)} checked, {pending} pending.")
    if pending == 0:
        print("nothing to label -- all pairs already checked.")
        return 0

    for entry in conversations:
        call_id = entry["call_id"]
        dims_pending = [d for d in JUDGE_DIMENSIONS if (call_id, d) not in done]
        if not dims_pending:
            continue
        try:
            document = load_source_document(entry["source"], root)
        except (OSError, ValueError) as exc:
            print(f"--- {call_id} ({entry['source']}): cannot load ({exc}) -- skipping.")
            continue
        print(f"--- {call_id} ({entry['source']}) ---")
        for line in render_transcript(document):
            print(f"  {line}")
        for dim_id in dims_pending:
            reference = reference_for(records, call_id, dim_id)
            outcome = _label_one_pair(
                call_id=call_id,
                dim_id=dim_id,
                reference=reference,
                rater=rater,
                labels_path=labels_path,
            )
            if outcome == "labeled":
                done.add((call_id, dim_id))
                counts[dim_id] = counts.get(dim_id, 0) + 1
                records = read_label_records(labels_path)
            elif outcome == "quit":
                print("quit -- progress saved (append-only); re-run to resume.")
                _print_counts(counts, len(conversations))
                return 0
    print("selection complete -- every pair now has a human verdict.")
    _print_counts(count_checked(read_label_records(labels_path)), len(conversations))
    return 0


def _print_counts(counts: dict[str, int], total: int) -> None:
    for dim_id in JUDGE_DIMENSIONS:
        print(f"  {dim_id}: {counts.get(dim_id, 0)}/{total} labeled")


def cmd_stats(args: argparse.Namespace) -> int:
    try:
        root = find_repo_root()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    selection_path = Path(args.selection)
    if not selection_path.exists():
        print(f"error: selection not found: {selection_path}", file=sys.stderr)
        return 2
    selection = load_selection(selection_path, root)
    conversations = selection.get("conversations", [])
    in_scope = {entry["call_id"] for entry in conversations}
    records = [
        record
        for record in read_label_records(args.labels)
        if record.call_id in in_scope
    ]
    counts = count_checked(records)
    print(f"labels: {args.labels} (selection: {len(conversations)} conversations)")
    _print_counts(counts, len(conversations))
    return 0


def cmd_selection(args: argparse.Namespace) -> int:
    try:
        root = find_repo_root()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    target = Path(args.selection)
    if args.rebuild:
        try:
            text = render_selection(build_selection(root))
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: cannot rebuild selection: {exc}", file=sys.stderr)
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        selection = load_selection(target, root)
        print(f"rebuilt {target}: {len(selection['conversations'])} conversations "
              f"(seed {selection['seed']}).")
        return 0
    if not target.exists():
        print(f"error: selection not found: {target}", file=sys.stderr)
        return 2
    selection = load_selection(target, root)
    print(f"selection: {len(selection['conversations'])} conversations "
          f"(seed {selection.get('seed')})")
    print(f"note: {selection.get('selection_note')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m turnstile_quality",
        description="Day-4 judge-calibration labeling tool ($0, stdlib only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    label = sub.add_parser("label", help="interactively hand-label (call, dim) pairs.")
    label.add_argument("--selection", required=True, help="selection.json manifest.")
    label.add_argument("--labels", required=True, help="labels JSONL file (append-only).")
    label.add_argument("--rater", required=True, help="rater name stamped on each row.")
    label.set_defaults(func=cmd_label)

    stats = sub.add_parser("stats", help="labeled/total per dimension.")
    stats.add_argument("--selection", required=True)
    stats.add_argument("--labels", required=True)
    stats.set_defaults(func=cmd_stats)

    selection = sub.add_parser("selection", help="inspect or rebuild the manifest.")
    selection.add_argument("--selection", required=True)
    selection.add_argument("--rebuild", action="store_true",
                           help="regenerate the manifest deterministically.")
    selection.set_defaults(func=cmd_selection)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
