"""Loop integration tests: a scripted text conversation emits a schema-valid
ingest call whose verdict/cost the REAL pipeline computes (price ->
adjudicate -> detect). Mock policy + mock tools + virtual clock: no LLM, no
audio, no network, fully deterministic."""
from __future__ import annotations

from pathlib import Path

from turnstile_ingest import parse_call, run_call
from turnstile_schema import Baselines, load_rates

from turnstile_live.loop import SCRIPTED_DEMO_TURNS, run_conversation

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate_json(
    (ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
)


def _demo_report():
    call = run_conversation(
        call_id="live-demo-001",
        scenario="billing_dispute",
        caller_turns=list(SCRIPTED_DEMO_TURNS),
    )
    return run_call(call.model_dump(mode="json"), RATES, BASELINES)


def test_emitted_call_validates_as_ingest():
    call = run_conversation(
        call_id="live-demo-001",
        scenario="billing_dispute",
        caller_turns=list(SCRIPTED_DEMO_TURNS),
    )
    parsed = parse_call(call.model_dump(mode="json"))
    assert parsed.id == "live-demo-001"
    assert len(parsed.turns) == len(SCRIPTED_DEMO_TURNS)
    assert all(turn.llm is not None for turn in parsed.turns)


def test_pipeline_prices_and_adjudicates_the_live_call():
    report = _demo_report()
    assert report["conv_cost_usd"] > 0.0
    assert report["verdict"]["label"] == "RESOLVED"
    # Typical real log: TTS text without G2 char counts -> acoustic classes
    # honestly ABSENT, telemetry classes present.
    assert report["coverage"]["6"]["status"] == "absent"
    assert report["coverage"]["7"]["status"] == "absent"
    assert report["coverage"]["8"]["status"] == "absent"
    assert report["coverage"]["1"]["status"] == "present"


def test_conversation_is_deterministic():
    kwargs = dict(
        call_id="live-demo-001",
        scenario="billing_dispute",
        caller_turns=list(SCRIPTED_DEMO_TURNS),
    )
    first = run_conversation(**kwargs).model_dump(mode="json")
    second = run_conversation(**kwargs).model_dump(mode="json")
    assert first == second


def test_each_turn_carries_caller_text_and_agent_reply():
    call = run_conversation(
        call_id="live-demo-001",
        scenario="billing_dispute",
        caller_turns=list(SCRIPTED_DEMO_TURNS),
    )
    for turn, expected_text in zip(call.turns, SCRIPTED_DEMO_TURNS):
        assert turn.asr is not None
        assert turn.asr.transcript == expected_text
        assert turn.llm is not None
        assert turn.llm.output_text
        assert turn.tts is not None
        assert turn.tts.text == turn.llm.output_text
