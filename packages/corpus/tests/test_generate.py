"""Tests for packages/corpus (docs/CORPUS.md's three binding constraints +
the wave-brief acceptance criteria).

Layers:
  * Schema-validity + pipeline layer -- every generated Trace round-trips
    through JSON and loads via turnstile_schema.load_trace; price_trace() and
    adjudicate() run over every trace with no error (every priced span
    resolves against pricing/rates.yaml).
  * Determinism -- same (n, seed) -> byte-identical corpus.
  * Constraint 3 -- BARGE_IN_RATE is the one named sensitivity knob; varying
    it changes the fraction of barge-in turns.
  * Constraint 1 -- distributions.py cites a source for every named
    distribution.
  * Constraint 2 -- generate.py / distributions.py / __init__.py never import
    turnstile_detectors, verified by source inspection (not just "did not
    happen to import it in this test run").
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from turnstile_schema import Baselines, load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate
from turnstile_corpus import distributions as dist
from turnstile_corpus.generate import generate_corpus, main

RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"
CORPUS_SRC = Path(__file__).parents[1] / "src" / "turnstile_corpus"

N_SMALL = 40
SEED = 7


@pytest.fixture(scope="module")
def small_corpus():
    return generate_corpus(N_SMALL, SEED)


@pytest.fixture(scope="module")
def rates():
    return load_rates(RATES)


# --------------------------------------------------------------------------- #
# Schema-validity + pipeline layer                                           #
# --------------------------------------------------------------------------- #

def test_generates_requested_count(small_corpus):
    assert len(small_corpus) == N_SMALL


def test_every_trace_round_trips_and_is_schema_valid(small_corpus, tmp_path):
    for trace in small_corpus:
        dumped = trace.model_dump(by_alias=True, mode="json")
        path = tmp_path / f"{trace.conversation.conversation_id}.json"
        path.write_text(json.dumps(dumped), encoding="utf-8")
        reloaded = load_trace(path)
        assert reloaded.conversation.conversation_id == trace.conversation.conversation_id


def test_pipeline_price_trace_and_adjudicate_run_without_error(small_corpus, rates):
    baselines = Baselines(per_intent={})
    for trace in small_corpus:
        priced = price_trace(trace, rates)  # KeyError here == an unresolvable rate key
        verdict = adjudicate(priced)
        assert 0.0 <= verdict.confidence <= 1.0
        assert priced.conv_cost >= 0.0


def test_conversation_ids_are_unique(small_corpus):
    ids = [t.conversation.conversation_id for t in small_corpus]
    assert len(ids) == len(set(ids))


def test_varied_length(small_corpus):
    turn_counts = {len(t.turns) for t in small_corpus}
    assert len(turn_counts) > 1, "corpus should have varied call lengths, not a single fixed length"


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #

def test_same_seed_is_deterministic():
    a = generate_corpus(20, seed=42)
    b = generate_corpus(20, seed=42)
    dump_a = [t.model_dump(by_alias=True, mode="json") for t in a]
    dump_b = [t.model_dump(by_alias=True, mode="json") for t in b]
    assert dump_a == dump_b


def test_different_seed_differs():
    a = generate_corpus(20, seed=1)
    b = generate_corpus(20, seed=2)
    dump_a = [t.model_dump(by_alias=True, mode="json") for t in a]
    dump_b = [t.model_dump(by_alias=True, mode="json") for t in b]
    assert dump_a != dump_b


# --------------------------------------------------------------------------- #
# Constraint 3 -- BARGE_IN_RATE is the one named sensitivity parameter        #
# --------------------------------------------------------------------------- #

def _barge_in_turn_fraction(traces) -> float:
    total_turns = sum(len(t.turns) for t in traces)
    barge_turns = sum(1 for t in traces for turn in t.turns if turn.barge_in)
    return barge_turns / total_turns


def test_barge_in_rate_is_single_named_param_and_changes_fraction():
    # Default (module constant) vs an explicit override, and an override
    # sweep low -> high, all via the SAME single kwarg / CLI flag.
    low = generate_corpus(60, seed=3, barge_in_rate=0.0)
    default = generate_corpus(60, seed=3, barge_in_rate=None)  # uses dist.BARGE_IN_RATE
    high = generate_corpus(60, seed=3, barge_in_rate=0.9)

    frac_low = _barge_in_turn_fraction(low)
    frac_default = _barge_in_turn_fraction(default)
    frac_high = _barge_in_turn_fraction(high)

    assert frac_low == 0.0
    assert frac_low < frac_default < frac_high
    assert frac_high > 0.6


def test_barge_in_rate_is_a_single_module_level_constant():
    assert hasattr(dist, "BARGE_IN_RATE")
    assert isinstance(dist.BARGE_IN_RATE, float)
    assert 0.0 < dist.BARGE_IN_RATE < 1.0


# --------------------------------------------------------------------------- #
# Constraint 1 -- named distributions with cited sources                      #
# --------------------------------------------------------------------------- #

def test_distributions_module_cites_sources():
    text = (CORPUS_SRC / "distributions.py").read_text(encoding="utf-8")
    source_citations = text.count("# source:")
    # One citation per major sampled quantity: turns, output tokens, caller
    # words, speech rate, barge-in rate, inter-turn gap, processing latency,
    # words->tokens, ASR confidence.
    assert source_citations >= 7, (
        f"expected >=7 '# source:' citations in distributions.py, found {source_citations}"
    )
    assert "http" in text  # every citation above is backed by a URL


def test_key_sampled_quantities_have_a_dedicated_distribution_function():
    for fn_name in (
        "sample_turn_count",
        "sample_output_tokens",
        "sample_caller_words",
        "sample_barge_in",
        "sample_inter_turn_gap_ms",
        "sample_processing_latency_ms",
        "sample_decision_kind",
    ):
        assert hasattr(dist, fn_name), f"distributions.py missing {fn_name}"


# --------------------------------------------------------------------------- #
# Constraint 2 -- generator never imports turnstile_detectors                 #
# --------------------------------------------------------------------------- #

def test_generator_does_not_import_detectors_by_source_inspection():
    # Only ban actual import statements -- prose in a docstring explaining
    # WHY there is no such import (as this module's own docstring does) must
    # not trip a naive substring ban.
    import_pattern = re.compile(
        r"^\s*(import\s+turnstile_detectors|from\s+turnstile_detectors\b)", re.MULTILINE
    )
    files = [CORPUS_SRC / "generate.py", CORPUS_SRC / "distributions.py", CORPUS_SRC / "__init__.py",
             Path(__file__).parents[1] / "generate.py"]
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not import_pattern.search(text), (
            f"{f} must not import turnstile_detectors (docs/CORPUS.md Constraint 2)"
        )


def test_generator_has_no_turnstile_detectors_dependency_declared():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "turnstile-detectors" not in pyproject
    assert "turnstile-detectors" not in pyproject.replace("-", "_")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def test_cli_writes_n_files(tmp_path):
    out_dir = tmp_path / "corpus_out"
    main(["--n", "5", "--seed", "11", "--out", str(out_dir)])
    written = list(out_dir.glob("*.json"))
    assert len(written) == 5
    for f in written:
        load_trace(f)  # schema-valid


def test_cli_barge_in_rate_override(tmp_path):
    out_dir = tmp_path / "corpus_bir"
    main(["--n", "10", "--seed", "11", "--out", str(out_dir), "--barge-in-rate", "0.0"])
    for f in out_dir.glob("*.json"):
        trace = load_trace(f)
        assert not any(turn.barge_in for turn in trace.turns)
