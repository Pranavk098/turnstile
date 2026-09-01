"""Tests for the reproducibility manifest (turnstile_experiments.manifest)."""
from __future__ import annotations

from pathlib import Path

from turnstile_schema.enums import DecisionKind

from turnstile_experiments import VARIANTS, build_manifest

from _experiments_builders import llm, priced, turn

ROOT = Path("pricing").resolve().parent  # repo root (tests run from there)
RATES_PATH = ROOT / "pricing" / "rates.yaml"


def _corpus():
    return [priced(turn(0, llm_spans=[llm("l0", decision_kind=DecisionKind.route)]),
                   conversation_id="c0")]


def test_manifest_records_provenance_and_applied_fields():
    corpus = _corpus()
    m = build_manifest(
        seed=0, n=len(corpus), backend_name="OpenAIBackend",
        variants=VARIANTS, corpus=corpus, rates_path=RATES_PATH, root=ROOT,
    )

    assert m["seed"] == 0
    assert m["n"] == 1
    assert m["backend"] == "OpenAIBackend"
    # git sha: 40-hex or the explicit "unknown" fallback, never silently blank.
    assert m["git_sha"] == "unknown" or len(m["git_sha"]) == 40
    assert len(m["rate_table_sha256"]) == 64  # sha256 hex
    assert m["corpus_model_ids"] == ["openai/gpt-5"]
    assert m["variant_route_targets"] == ["gpt-5-nano"]

    # The load-bearing field: what the replay engine ACTUALLY applied.
    v = m["variants"]["model_routing_gpt5_nano"]
    assert v["set_fields"] == ["model_routing"]
    assert v["applied_fields"] == ["model_routing"]


def test_manifest_rate_hash_is_stable():
    corpus = _corpus()
    a = build_manifest(seed=1, n=1, backend_name="MockBackend",
                       variants=VARIANTS, corpus=corpus, rates_path=RATES_PATH, root=ROOT)
    b = build_manifest(seed=1, n=1, backend_name="MockBackend",
                       variants=VARIANTS, corpus=corpus, rates_path=RATES_PATH, root=ROOT)
    assert a["rate_table_sha256"] == b["rate_table_sha256"]
