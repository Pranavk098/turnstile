import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from turnstile_schema import (
    Baselines,
    ExperimentResult,
    Finding,
    IntentBaseline,
    PricedTrace,
    Trial,
    Verdict,
    VariantSpec,
)
from turnstile_schema.trace import Trace

FIXTURES = Path(__file__).parents[3] / "fixtures" / "sample"

MINIMAL_TRACE = {
    "conversation": {
        "conversation_id": "c1", "agent_version": "v1", "scenario_id": "order_status",
        "started_at": "2026-08-30T00:00:00Z", "ended_at": "2026-08-30T00:00:30Z",
        "end_reason": "caller_hangup"},
    "turns": [{
        "turn_index": 0, "speaker_first": "caller",
        "wall_start_ms": 0, "wall_end_ms": 3000,
        "llm": [{
            "span_id": "l0",
            "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 300,
            "gen_ai.system": "openai", "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 500, "gen_ai.usage.output_tokens": 20,
            "turnstile.decision_kind": "compose", "turnstile.decision_chosen": "greet",
            "turnstile.decision_candidates": ["greet"], "turnstile.output_text": "hello",
            "turnstile.latency_ms": 300}]}],
}


def test_priced_trace_round_trips():
    pt = PricedTrace(
        trace=Trace.model_validate(MINIMAL_TRACE),
        span_costs={"l0": 0.001},
        turn_costs=[0.001],
        conv_cost=0.001,
        stage_costs={"asr": 0.0, "llm": 0.001, "tts": 0.0, "telephony": 0.0},
    )
    assert pt.conv_cost == 0.001
    assert pt.stage_costs["llm"] == 0.001


def test_variant_spec_all_fields_optional():
    vs = VariantSpec()
    assert vs.model_routing is None
    assert vs.tool_batching is None

    vs2 = VariantSpec(
        model_routing={"route": "haiku", "compose": "sonnet"},
        context_strategy="window:8",
        prefix_caching=True,
        retrieval_policy="threshold:0.8",
        tts_chunking="sentence",
        escalation_policy="threshold:0.85",
        tool_batching=True,
    )
    assert vs2.model_routing == {"route": "haiku", "compose": "sonnet"}


def test_finding_requires_proposed_variant():
    with pytest.raises(ValidationError):
        Finding(
            class_id=1, turn_index=0, span_id="l0",
            waste_usd=0.01, confidence=0.9, evidence={},
        )


def test_finding_valid_instance():
    f = Finding(
        class_id=1, turn_index=0, span_id="l0",
        waste_usd=0.01, confidence=0.9,
        proposed_variant=VariantSpec(model_routing={"route": "haiku"}),
        evidence={"why": "frontier model on trivial decision"},
    )
    assert f.class_id == 1
    assert f.proposed_variant.model_routing == {"route": "haiku"}


def test_finding_class_id_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Finding(
            class_id=11, turn_index=0, span_id="l0",
            waste_usd=0.01, confidence=0.9,
            proposed_variant=VariantSpec(), evidence={},
        )


def test_finding_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Finding(
            class_id=1, turn_index=0, span_id="l0",
            waste_usd=0.01, confidence=5.0,
            proposed_variant=VariantSpec(), evidence={},
        )


def test_finding_confidence_in_range_constructs():
    f = Finding(
        class_id=1, turn_index=0, span_id="l0",
        waste_usd=0.01, confidence=0.5,
        proposed_variant=VariantSpec(), evidence={},
    )
    assert f.confidence == 0.5


def test_verdict_valid_instance():
    v = Verdict(
        label="RESOLVED", confidence=0.95,
        evidence=[{"source": "terminal_tool_state", "effect": "committed"}],
        turn_of_no_return=2,
    )
    assert v.label.value == "RESOLVED"
    assert v.turn_of_no_return == 2


def test_verdict_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Verdict(
            label="RESOLVED", confidence=-1,
            evidence=[], turn_of_no_return=None,
        )


def test_verdict_confidence_in_range_constructs():
    v = Verdict(
        label="UNRESOLVED", confidence=0.6,
        evidence=[], turn_of_no_return=None,
    )
    assert v.confidence == 0.6


def test_baselines_valid_instance():
    b = Baselines(per_intent={
        "order_status": IntentBaseline(
            p50_turns=3.0, p75_turns=5.0, mean_cost_per_turn=0.02),
    })
    assert b.per_intent["order_status"].p50_turns == 3.0


def test_trial_valid_instance():
    t = Trial(
        trace_id="c1", status="ok",
        delta_cost=-0.02, delta_latency_ms=-150.0, outcome_preserved=True,
    )
    assert t.status == "ok"


def test_experiment_result_valid_instance():
    er = ExperimentResult(
        n=200, outcome_preservation_rate=0.97,
        delta_cost_mean=-0.015, delta_cost_ci95=(-0.02, -0.01),
        delta_latency_p50=-120.0, delta_latency_p95=-80.0,
        divergent_exemplars=["c42", "c99"],
    )
    assert er.delta_cost_ci95 == (-0.02, -0.01)


def test_sample_findings_file_loads_and_validates():
    data = json.loads((FIXTURES / "findings.sample.json").read_text(encoding="utf-8"))
    findings = [Finding.model_validate(f) for f in data]
    assert len(findings) >= 1
    for f in findings:
        assert f.proposed_variant is not None


def test_sample_experiments_file_loads_and_validates():
    data = json.loads((FIXTURES / "experiments.sample.json").read_text(encoding="utf-8"))
    results = [ExperimentResult.model_validate(e) for e in data]
    assert len(results) >= 1
