"""Contract compliance for detect() (PRD §5): runs cleanly over every golden
fixture and every emitted Finding satisfies the frozen Finding contract,
including "a detector that cannot propose a testable alternative may not emit
a finding" (PRD §6) -- every proposed_variant must set at least one knob.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from turnstile_schema import Baselines, Finding, Verdict, load_rates, load_trace
from turnstile_schema.enums import VerdictLabel
from turnstile_pricing import price_trace
from turnstile_detectors import detect

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

_DUMMY_VERDICT = Verdict(label=VerdictLabel.RESOLVED, confidence=1.0, evidence=[], turn_of_no_return=None)
_EMPTY_BASELINES = Baselines(per_intent={})


def _fixture_ids() -> list[str]:
    return [f["id"] for f in yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]]


def _findings(fid: str) -> list[Finding]:
    trace = load_trace((GOLDEN / fid).with_suffix(".json"))
    priced = price_trace(trace, load_rates(RATES))
    return detect(priced, _DUMMY_VERDICT, _EMPTY_BASELINES)


@pytest.mark.parametrize("fid", _fixture_ids())
def test_detect_runs_clean_on_every_golden_fixture(fid):
    findings = _findings(fid)
    assert isinstance(findings, list)
    assert all(isinstance(f, Finding) for f in findings)


@pytest.mark.parametrize("fid", _fixture_ids())
def test_every_finding_has_a_non_trivial_proposed_variant(fid):
    for f in _findings(fid):
        assert f.proposed_variant is not None
        variant_dict = f.proposed_variant.model_dump()
        assert any(v is not None for v in variant_dict.values()), (
            f"class {f.class_id} finding on {fid} proposed an empty VariantSpec"
        )


@pytest.mark.parametrize("fid", _fixture_ids())
def test_every_finding_references_a_real_span_in_its_turn(fid):
    trace = load_trace((GOLDEN / fid).with_suffix(".json"))
    for f in _findings(fid):
        turn = trace.turns[f.turn_index]
        real_span_ids = {
            s.span_id
            for group in (turn.vad, turn.asr, turn.llm, turn.tools, turn.tts, turn.playback)
            for s in group
        }
        # D8 may synthesize a "no active span yet" placeholder id for a
        # leading silence gap (see turnstile_detectors.d08_silence_tax).
        assert f.span_id in real_span_ids or f.span_id.startswith(f"turn{f.turn_index}:")


def test_00_baseline_clean_fires_nothing():
    assert _findings("00_baseline_clean") == []


def test_waste_usd_is_never_negative():
    for fid in _fixture_ids():
        for f in _findings(fid):
            assert f.waste_usd >= 0, f"class {f.class_id} on {fid} has negative waste_usd"
