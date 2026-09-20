"""Day-4 Part E paid reference pre-labeler (setup phase only).

Reads Part A's ``fixtures/calibration/selection.json``, calls a paid model
once per (call, dimension) pair, and merges reference pre-labels into
``fixtures/calibration/labels.jsonl`` as ``reference_label`` /
``reference_confidence`` rows (``human_*`` left null for the rater's CLI
session). Every paid call is logged to
``fixtures/calibration/reference_log.jsonl`` with tokens, cost, and a
running total.

SAFETY (charter $0 rule):
- Refuses unless BOTH ``TURNSTILE_ALLOW_PAID=1`` AND ``--spend-ack`` are
  present (``--dry-run`` bypasses the gates: it performs no network, no
  spend, and no writes).
- Prints the cost estimate BEFORE the first paid call.
- Hard ``--max-usd`` cap: aborts before exceeding it, keeping completed
  labels.
- Model output is strict-parsed for pass/fail + confidence in [0, 1];
  parse failures are logged and skipped, NEVER guessed.
- Never referenced from CI (no workflow may import or call this script).
- API key is read from ``OPENAI_API_KEY``; only the variable NAME is ever
  reported, never its value.

Run from the repo root::

    uv run python scripts/reference_label.py --dry-run
    uv run python scripts/reference_label.py --spend-ack --max-usd 2.00

Transport is stdlib ``urllib`` only (no new dependencies).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover - runner convenience
    sys.path.insert(0, str(ROOT))

from turnstile_quality.calibration import JUDGE_DIMENSIONS
from turnstile_quality.labeling import (
    LabelRecord,
    append_label_record,
    find_repo_root,
    load_selection,
    load_source_document,
    read_label_records,
    reference_for,
    render_transcript,
)

# ---------------------------------------------------------------------------
# Pinned reproducibility constants (echoed into every log row).
# ---------------------------------------------------------------------------

MODEL_ID = "gpt-4o-mini"
TEMPERATURE = 0

PROMPT_TEMPLATE = """You are grading a voice-agent call for ONE quality dimension.
Dimension: {dim_id}
Rubric: {rubric}

Transcript (caller/agent text per turn):
{transcript}

Reply with a single JSON object and nothing else, using EXACTLY these keys:
{{"label": "pass" or "fail", "confidence": <number in [0, 1]>}}
"pass" means the call satisfies the rubric; "fail" means it does not.
"confidence" is your certainty that the label is correct (0 = guessing, 1 = certain).
"""

PROMPT_HASH = hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()

DIM_RUBRICS = {
    "faithfulness": (
        "Every substantive claim the agent makes is grounded in the call "
        "context (caller statements, tool outputs, known state). No invented "
        "facts, no contradicting earlier turns."
    ),
    "answer_relevance": (
        "Each agent response addresses what the caller just asked or needed. "
        "No evasions, no off-topic filler, no ignoring the request."
    ),
}

# gpt-4o-mini list pricing at time of writing (USD per 1M tokens).
PRICE_INPUT_USD_PER_1M = 0.15
PRICE_OUTPUT_USD_PER_1M = 0.60

# Planning estimate per paid call (generous upper bound for budgeting).
EST_INPUT_TOKENS_PER_CALL = 3000
EST_OUTPUT_TOKENS_PER_CALL = 100

# Hard spend cap default (USD). Rationale: the planning estimate for the full
# run (60 conversations x 2 dims = 120 calls) is ~$0.06, so $2.00 allows
# ~30x headroom for longer transcripts/retries while staying trivially small.
DEFAULT_MAX_USD = 2.00

API_KEY_ENV = "OPENAI_API_KEY"
GATE_ENV = "TURNSTILE_ALLOW_PAID"

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

#: Exit code for a clean cap-abort (completed labels are kept).
EXIT_CAP_ABORTED = 3


def estimate_cost_usd(tokens_in: int, tokens_out: int) -> float:
    """USD cost of one call from token counts and the pinned prices."""
    return (
        tokens_in / 1_000_000 * PRICE_INPUT_USD_PER_1M
        + tokens_out / 1_000_000 * PRICE_OUTPUT_USD_PER_1M
    )


def estimate_full_run_usd(n_pairs: int) -> float:
    """Planning estimate for ``n_pairs`` paid calls (upper bound)."""
    return n_pairs * estimate_cost_usd(
        EST_INPUT_TOKENS_PER_CALL, EST_OUTPUT_TOKENS_PER_CALL
    )


def build_prompt(call_id: str, dim_id: str, transcript_lines: list[str]) -> str:
    """Render the pinned prompt template for one (call, dim) pair."""
    return PROMPT_TEMPLATE.format(
        dim_id=dim_id,
        rubric=DIM_RUBRICS[dim_id],
        transcript="\n".join(transcript_lines),
    )


class ParseError(ValueError):
    """Model output did not strict-parse (never guessed past)."""


def parse_model_output(raw: str) -> tuple[str, float]:
    """Strict-parse ``{"label": pass|fail, "confidence": [0,1]}``.

    Raises :class:`ParseError` on ANY deviation (non-JSON, wrong keys,
    unknown label, out-of-range/non-finite confidence). Callers MUST log
    and skip -- never guess.
    """
    try:
        payload = json.loads(raw.strip())
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ParseError(f"top-level JSON must be an object, got {type(payload).__name__}")
    if set(payload) != {"label", "confidence"}:
        raise ParseError(f"keys must be exactly label+confidence, got {sorted(payload)}")
    label = payload["label"]
    if label not in ("pass", "fail"):
        raise ParseError(f"label must be 'pass' or 'fail', got {label!r}")
    confidence = payload["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ParseError(f"confidence must be a number in [0, 1], got {confidence!r}")
    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ParseError(f"confidence must be a finite float in [0, 1], got {confidence!r}")
    return label, confidence


#: Model client: prompt -> (raw response text, input tokens, output tokens).
ModelClient = Callable[[str], tuple[str, int, int]]


def real_openai_client(api_key: str, timeout_s: float = 60.0) -> ModelClient:
    """Build the stdlib-urllib client for the pinned model (paid)."""

    def _call(prompt: str) -> tuple[str, int, int]:
        body = json.dumps(
            {
                "model": MODEL_ID,
                "temperature": TEMPERATURE,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        return raw, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    return _call


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_log_row(log_path: Path, row: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def check_spend_gates(spend_ack: bool) -> str | None:
    """Return a refusal message unless BOTH spend gates hold, else None."""
    if os.environ.get(GATE_ENV) != "1":
        return (
            f"refusing: paid spend gate closed ({GATE_ENV} != '1'). "
            f"To opt in, set {GATE_ENV}=1 in the environment AND pass --spend-ack. "
            "No network call was made, nothing was written."
        )
    if not spend_ack:
        return (
            "refusing: explicit --spend-ack flag missing. "
            f"({GATE_ENV}=1 is set, but the spend requires the flag too.) "
            "Re-run with --spend-ack to acknowledge the charge. "
            "No network call was made, nothing was written."
        )
    return None


def pending_pairs(selection: dict, records: list[LabelRecord]) -> list[tuple[str, str]]:
    """(call, dim) pairs lacking a reference pre-label, in selection order."""
    pairs: list[tuple[str, str]] = []
    for entry in selection.get("conversations", []):
        for dim_id in JUDGE_DIMENSIONS:
            if reference_for(records, entry["call_id"], dim_id) is None:
                pairs.append((entry["call_id"], entry["source"], dim_id))
    return pairs


def run_reference_labeling(
    *,
    selection: dict,
    root: Path,
    labels_path: Path,
    log_path: Path,
    max_usd: float,
    call_model: ModelClient,
    dry_run: bool = False,
    out: Callable[[str], None] = print,
) -> dict:
    """Label every pending pair via ``call_model`` (injected for testability).

    Returns a summary dict (n_pairs, n_ok, n_parse_errors, n_skipped_cap,
    spend_usd, cap_aborted). In ``dry_run`` mode no network/spend/writes
    happen: selection iteration + transcript rendering + prompt building +
    cap simulation only.
    """
    records = read_label_records(labels_path) if not dry_run else []
    if dry_run:
        # Dry-run still reads the REAL labels file for resume math, without
        # importing its rows anywhere writable.
        records = read_label_records(labels_path)
    pairs = pending_pairs(selection, records)
    n_total = len(selection.get("conversations", [])) * len(JUDGE_DIMENSIONS)
    out(
        f"selection: {len(selection.get('conversations', []))} conversations x "
        f"{len(JUDGE_DIMENSIONS)} dims = {n_total} pairs; "
        f"{n_total - len(pairs)} already pre-labeled, {len(pairs)} pending."
    )
    if dry_run:
        out("DRY-RUN: no network, no spend, no writes. Rendering only.")
    est_total = estimate_full_run_usd(len(pairs))
    out(
        f"cost estimate: {len(pairs)} pending calls x "
        f"(${estimate_cost_usd(EST_INPUT_TOKENS_PER_CALL, EST_OUTPUT_TOKENS_PER_CALL):.5f}/call) "
        f"= ~${est_total:.4f} (model {MODEL_ID}, cap ${max_usd:.2f})."
    )

    running_total = 0.0
    n_ok = 0
    n_parse_errors = 0
    n_cap_skipped = 0
    for index, (call_id, source, dim_id) in enumerate(pairs):
        try:
            document = load_source_document(source, root)
        except (OSError, ValueError) as exc:
            out(f"  {call_id}/{dim_id}: cannot load source ({exc}) -- skipping.")
            continue
        transcript_lines = render_transcript(document)
        prompt = build_prompt(call_id, dim_id, transcript_lines)
        est_next = estimate_cost_usd(EST_INPUT_TOKENS_PER_CALL, EST_OUTPUT_TOKENS_PER_CALL)

        if dry_run:
            # Simulate the cap against the planning estimate (no spend).
            if running_total + est_next > max_usd:
                n_cap_skipped = len(pairs) - index
                out(
                    f"  {call_id}/{dim_id}: [dry-run] cap would abort here "
                    f"(running ~${running_total:.4f} + est ~${est_next:.4f} > ${max_usd:.2f}); "
                    "stopping."
                )
                break
            running_total += est_next
            out(
                f"  {call_id}/{dim_id}: [dry-run] transcript {len(transcript_lines)} lines, "
                f"prompt {len(prompt)} chars, est ~${est_next:.5f} "
                f"(running ~${running_total:.4f})."
            )
            continue

        # Hard cap: abort BEFORE exceeding it; completed labels are kept.
        if running_total + est_next > max_usd:
            out(
                f"CAP REACHED: stopping before {call_id}/{dim_id} "
                f"(running ${running_total:.4f} + est ${est_next:.4f} > cap ${max_usd:.2f}). "
                f"Kept {n_ok} completed labels."
            )
            n_cap_skipped = len(pairs) - index
            return {
                "n_pairs": len(pairs),
                "n_ok": n_ok,
                "n_parse_errors": n_parse_errors,
                "n_skipped_cap": n_cap_skipped,
                "spend_usd": running_total,
                "cap_aborted": True,
            }
        try:
            raw, tokens_in, tokens_out = call_model(prompt)
        except Exception as exc:  # network/API failure: log, skip, continue
            cost = 0.0
            append_log_row(
                log_path,
                {
                    "ts": _now_iso(),
                    "call_id": call_id,
                    "dim_id": dim_id,
                    "model": MODEL_ID,
                    "prompt_hash": PROMPT_HASH,
                    "temperature": TEMPERATURE,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_usd": cost,
                    "running_total_usd": round(running_total, 6),
                },
            )
            out(f"  {call_id}/{dim_id}: call failed ({exc}) -- logged, skipped.")
            continue
        cost = estimate_cost_usd(tokens_in, tokens_out)
        running_total += cost
        try:
            label, confidence = parse_model_output(raw)
        except ParseError as exc:
            append_log_row(
                log_path,
                {
                    "ts": _now_iso(),
                    "call_id": call_id,
                    "dim_id": dim_id,
                    "model": MODEL_ID,
                    "prompt_hash": PROMPT_HASH,
                    "temperature": TEMPERATURE,
                    "status": "parse_error",
                    "error": str(exc),
                    "raw_excerpt": raw[:500],
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": round(cost, 6),
                    "running_total_usd": round(running_total, 6),
                },
            )
            n_parse_errors += 1
            out(f"  {call_id}/{dim_id}: parse failure -- logged, skipped (never guessed).")
            continue
        append_log_row(
            log_path,
            {
                "ts": _now_iso(),
                "call_id": call_id,
                "dim_id": dim_id,
                "model": MODEL_ID,
                "prompt_hash": PROMPT_HASH,
                "temperature": TEMPERATURE,
                "status": "ok",
                "label": label,
                "confidence": confidence,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": round(cost, 6),
                "running_total_usd": round(running_total, 6),
            },
        )
        append_label_record(
            labels_path,
            LabelRecord(
                call_id=call_id,
                dim_id=dim_id,
                reference_label=label,  # type: ignore[arg-type]
                reference_confidence=confidence,
                human_label=None,
                rater=None,
                checked_at=None,
                note=f"reference pre-label ({MODEL_ID}, prompt {PROMPT_HASH[:12]}); awaiting human check",
            ),
        )
        n_ok += 1
        out(
            f"  {call_id}/{dim_id}: {label} ({confidence:.2f}) "
            f"${cost:.5f} (running ${running_total:.4f})."
        )
    out(
        f"done: {n_ok} pre-labeled, {n_parse_errors} parse errors, "
        f"{n_cap_skipped} cap-skipped; spend ${running_total:.4f} (cap ${max_usd:.2f})."
    )
    return {
        "n_pairs": len(pairs),
        "n_ok": n_ok,
        "n_parse_errors": n_parse_errors,
        "n_skipped_cap": n_cap_skipped,
        "spend_usd": running_total,
        "cap_aborted": n_cap_skipped > 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Paid reference pre-labeler for Day-4 calibration (opt-in, capped, logged).",
    )
    parser.add_argument("--selection", default="fixtures/calibration/selection.json")
    parser.add_argument("--labels", default="fixtures/calibration/labels.jsonl")
    parser.add_argument("--log", default="fixtures/calibration/reference_log.jsonl")
    parser.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD)
    parser.add_argument(
        "--spend-ack",
        action="store_true",
        help="explicitly acknowledge the paid spend (required with TURNSTILE_ALLOW_PAID=1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="no network, no spend, no writes: iterate selection + render transcripts only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_usd <= 0:
        print("error: --max-usd must be positive.", file=sys.stderr)
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
    for dim_id in JUDGE_DIMENSIONS:
        if dim_id not in DIM_RUBRICS:
            print(f"error: no rubric pinned for dimension {dim_id!r}.", file=sys.stderr)
            return 2

    if args.dry_run:
        print("dry-run mode: spend gates do not apply (nothing can be spent or written).")
        print(f"model: {MODEL_ID} | temperature: {TEMPERATURE} | prompt sha256: {PROMPT_HASH}")
        summary = run_reference_labeling(
            selection=selection,
            root=root,
            labels_path=Path(args.labels),
            log_path=Path(args.log),
            max_usd=args.max_usd,
            call_model=lambda prompt: (_ for _ in ()).throw(
                AssertionError("dry-run must not call the model")
            ),
            dry_run=True,
        )
        return EXIT_CAP_ABORTED if summary["cap_aborted"] else 0

    refusal = check_spend_gates(args.spend_ack)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        print(
            f"refusing: {API_KEY_ENV} is not set (checked by name only). "
            "Set it in the environment, then re-run. "
            "No network call was made, nothing was written.",
            file=sys.stderr,
        )
        return 2

    print(f"model: {MODEL_ID} | temperature: {TEMPERATURE} | prompt sha256: {PROMPT_HASH}")
    print(f"spend gates passed ({GATE_ENV}=1 + --spend-ack). Estimated cost follows -- review before proceeding.")
    summary = run_reference_labeling(
        selection=selection,
        root=root,
        labels_path=Path(args.labels),
        log_path=Path(args.log),
        max_usd=args.max_usd,
        call_model=real_openai_client(api_key),
    )
    return EXIT_CAP_ABORTED if summary["cap_aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
