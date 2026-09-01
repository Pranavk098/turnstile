"""Reproducibility manifest for an experiment run.

Records exactly what would be needed to reproduce (or defend) a headline
number: the corpus seed and size, the git commit, a content hash of the rate
table (rates.yaml carries no version field), the backend, the distinct model
ids the run actually calls, and -- per variant -- WHICH VariantSpec fields the
replay engine actually applied (vs merely set). That last item is the direct
answer to "is this saving replay-proven?": if ``applied_fields`` is empty, it
isn't.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import subprocess
from pathlib import Path

from turnstile_schema import PricedTrace, VariantSpec

from turnstile_experiments.guard import applied_fields, set_fields


def _git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _rate_table_sha256(rates_path: Path) -> str:
    try:
        return hashlib.sha256(rates_path.read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def _corpus_model_ids(corpus: list[PricedTrace]) -> list[str]:
    """Distinct ``{gen_ai_system}/{model}`` ids the corpus's llm decisions use
    (the models a replay actually calls when a variant doesn't reroute them)."""
    ids: set[str] = set()
    for pt in corpus:
        for turn in pt.trace.turns:
            for span in turn.llm:
                ids.add(f"{span.gen_ai_system}/{span.gen_ai_request_model}")
    return sorted(ids)


def _variant_model_targets(variants: dict[str, VariantSpec]) -> list[str]:
    """Distinct models the executable variants route decisions TO."""
    targets: set[str] = set()
    for v in variants.values():
        if v.model_routing:
            targets.update(v.model_routing.values())
    return sorted(targets)


def build_manifest(
    *,
    seed: int,
    n: int,
    backend_name: str,
    variants: dict[str, VariantSpec],
    corpus: list[PricedTrace],
    rates_path: Path,
    root: Path,
) -> dict:
    return {
        "git_sha": _git_sha(root),
        "rate_table_path": str(rates_path.relative_to(root)) if _is_relative(rates_path, root) else str(rates_path),
        "rate_table_sha256": _rate_table_sha256(rates_path),
        "seed": seed,
        "n": n,
        "backend": backend_name,
        "corpus_model_ids": _corpus_model_ids(corpus),
        "variant_route_targets": _variant_model_targets(variants),
        "variants": {
            name: {
                "set_fields": sorted(set_fields(v)),
                "applied_fields": sorted(applied_fields(v)),
            }
            for name, v in variants.items()
        },
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
