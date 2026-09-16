"""Retell adapter tests (Day-2 Track A): mapping, loud failure, honesty boundaries.

Conventions mirror test_vapi.py: the committed
``sample/retell-export.sample.json`` (Track B) as the golden fixture plus
small inline Retell exports built by the helpers below for the error-path
and unit pins.

Imports come from ``turnstile_ingest.providers.retell`` directly: Track B
owns the top-level re-exports in ``turnstile_ingest/__init__.py``, so this
file must not import retell names from the package root (namespaced imports
keep working whatever B wires).

Every test pins an honesty invariant -- inferred labels flagged, absent data
ABSENT (never zeroed), unmappable input loud.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from turnstile_detectors import detect
from turnstile_pricing import price_trace
from turnstile_schema import Baselines, load_rates
from turnstile_verdict import adjudicate
from turnstile_ingest import (
    IngestError,
    describe_coverage,
    load,
    run_call,
    run_calls,
)
from turnstile_ingest.providers.retell import (
    from_retell,
    from_retell_export,
    inferred_decision_turns,
    map_end_reason,
    provider_info,
)

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate({"per_intent": {
    "billing_assistant": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
    "order_status": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
}})
# Track B's committed sample: the golden fixture (labeled synthetic in-file).
RETELL_SAMPLE_PATH = ROOT / "packages" / "ingest" / "sample" / "retell-export.sample.json"
SAMPLE = json.loads(RETELL_SAMPLE_PATH.read_text(encoding="utf-8"))

BASE_MS = 1789203731000  # epoch ms of the golden call's start_timestamp
LLM = ("openai", "gpt-5-mini")


def _words(text, start_s, step=0.25, dur=0.2):
    words = []
    cursor = start_s
    for word in text.split():
        words.append({"word": word, "start": round(cursor, 3),
                      "end": round(cursor + dur, 3)})
        cursor += step
    return words


def _utt(role, content, start_s):
    return {"role": role, "content": content, "words": _words(content, start_s)}


def _invoke(call_id, name, args, **extra):
    return {"role": "tool_call_invocation", "tool_call_id": call_id,
            "name": name, "arguments": json.dumps(args), **extra}


def _result(call_id, content, successful=True, *, omit_successful=False):
    node = {"role": "tool_call_result", "tool_call_id": call_id,
            "content": content}
    if not omit_successful:
        node["successful"] = successful
    return node


def _retell_call(entries, *, call_id="retell-test-001", with_tools=True,
                 transcript_object=None, **overrides):
    call = {
        "call_id": call_id,
        "agent_id": "agent-test-001",
        "agent_name": "Billing Assistant",
        "agent_version": 3,
        "call_status": "ended",
        "call_type": "phone_call",
        "direction": "inbound",
        "from_number": "+15550001111",
        "to_number": "+15550002222",
        "start_timestamp": BASE_MS,
        "end_timestamp": BASE_MS + 30000,
        "duration_ms": 30000,
        "disconnection_reason": "user_hangup",
        "llm_token_usage": {"values": [975, 975, 975, 975], "average": 975.0,
                            "num_requests": 4},
    }
    if with_tools:
        call["transcript_with_tool_calls"] = entries
    if transcript_object is None:
        transcript_object = [entry for entry in entries
                             if isinstance(entry, dict)
                             and str(entry.get("role") or "")
                             in ("agent", "user", "transfer_target")]
    call["transcript_object"] = transcript_object
    call.update(overrides)
    return call


def _adapt(call_obj, **kwargs):
    kwargs.setdefault("llm_identity", LLM)
    return from_retell(call_obj, **kwargs)


def _golden_call(**overrides):
    """Four-turn billing dispute mirroring the Vapi sample's narrative.

    Greeting + complaint + invoice lookup + authorized correction + close;
    agent_version int, phone_call inbound, word-timed utterances throughout.
    """
    entries = [
        _utt("agent", "Hi, thanks for calling Acme support. How can I help?", 0.0),
        _utt("user", "Hi, I was charged twice for my July bill, can you fix that?", 2.6),
        _invoke("toolu_01lookup001", "lookup_invoices", {"customer_id": "C-10293"}),
        _result("toolu_01lookup001",
                '{"invoices": [{"id": "INV-8821", "amount": 79.0, "status": "paid"}, '
                '{"id": "INV-8822", "amount": 79.0, "status": "duplicate"}]}'),
        _utt("agent", "I found the duplicate charge from July. I will apply a correction now.", 7.4),
        _utt("user", "Yes, please fix it.", 11.2),
        _invoke("toolu_01adjust002", "adjust_billing",
                {"customer_id": "C-10293", "invoice_id": "INV-8822"}),
        _result("toolu_01adjust002",
                '{"status": "refunded", "amount": 79.0, "invoice_id": "INV-8822"}'),
        _utt("agent", "Done -- I have refunded the duplicate charge of 79 dollars. Anything else?", 14.8),
        _utt("user", "No, that is all. Thanks, bye!", 17.8),
        _utt("agent", "You are welcome. Goodbye!", 19.8),
    ]
    call = _retell_call(
        entries, call_id="retell-golden-001", agent_id="agent-billing-synthetic",
        llm_token_usage={"values": [1000, 1100, 900, 900], "average": 975.0,
                         "num_requests": 4},
    )
    call.update(overrides)
    return call


def _route_probe_call():
    """Three-utterance export whose opening route turn WOULD fire D1 (frontier
    gpt-5, short output) if its decision_kind were agent-emitted. Two LLM
    turns so partial-inference gating has something to split."""
    return _retell_call(
        [_utt("agent", "How can I help?", 0.0),
         _utt("user", "Where is my order?", 1.5),
         _utt("agent", "One moment, checking now.", 3.5)],
        call_id="retell-d1-probe", agent_name="Order Status",
        llm_token_usage={"values": [800, 900], "average": 850.0, "num_requests": 2},
    )


def _prov(call_obj, adapted=None, **kwargs):
    adapted = adapted if adapted is not None else _adapt(call_obj)
    return {adapted.id: provider_info(call_obj, adapted, **kwargs)}


# --------------------------------------------------------------------------- #
# Golden sample mapping (field-level assertions, mirrors test_vapi.py)          #
# --------------------------------------------------------------------------- #

def test_sample_file_is_labeled_synthetic():
    assert SAMPLE["sample"] is True
    assert "NOT real customer traffic" in SAMPLE["_note"]


def test_sample_maps_to_expected_ingest_call():
    call = _adapt(SAMPLE)
    assert call.id == "synth-retell-billing-0001"
    assert call.scenario == "billing_assistant"
    assert call.end_reason.value == "caller_hangup"
    assert call.agent_version == "retell/agent-synthetic-billing-01.v3"
    assert call.telephony is not None
    assert call.telephony.billable_seconds == 30
    assert call.telephony.direction.value == "inbound"
    assert len(call.turns) == 4

    opening, middle, mutation, close = call.turns
    # Turn grouping: greeting-first turn, then one turn per caller utterance.
    assert opening.asr is None and opening.speaker_first.value == "agent"
    assert middle.asr is not None and middle.asr.transcript.startswith("Hi, I was charged twice")
    assert mutation.asr is not None and mutation.asr.transcript == "Yes, please fix it."
    assert close.asr is not None and "Thanks, bye" in close.asr.transcript

    # Inference rules: route-first, tool_select-on-mutation, compose.
    assert opening.llm.decision_kind.value == "route"
    assert opening.llm.decision == "billing_assistant"
    assert opening.llm.decision_candidates == ["billing_assistant", "other"]
    assert middle.llm.decision_kind.value == "compose"
    assert mutation.llm.decision_kind.value == "tool_select"
    assert mutation.llm.decision == "adjust_billing"
    assert close.llm.decision_kind.value == "compose"

    # output_text is the agent's own utterance -- never empty, never tool text.
    assert opening.llm.output_text.startswith("Hi, thanks for calling")
    assert "refunded the duplicate" in mutation.llm.output_text

    # Tools: lookup reads effect=none; committed mutation resolves committed.
    lookup = middle.tools[0]
    assert (lookup.name, lookup.kind.value, lookup.effect.value) == (
        "lookup_invoices", "lookup", "none")
    adjust = mutation.tools[0]
    assert (adjust.name, adjust.kind.value, adjust.effect.value,
            adjust.status.value) == ("adjust_billing", "mutation", "committed", "ok")

    # Tokens: Retell emits only a combined total -- exact-sum even split lands
    # in input_tokens with output_tokens 0 (output unmeasured, not zero).
    assert sum(t.llm.input_tokens for t in call.turns) == 1050 + 980 + 1020 + 1000
    assert all(t.llm.output_tokens == 0 for t in call.turns)
    assert all(t.llm.cache_read_tokens == 0 for t in call.turns)

    # TTS text rides along but char counts are absent (G2: no stand-in).
    assert all(t.tts is not None and t.tts.text for t in call.turns)
    assert all(t.tts.chars_synthesized is None and t.tts.chars_played is None
               for t in call.turns)


def test_sample_loads_and_prices_with_no_acoustic_spans():
    call = _adapt(SAMPLE)
    trace = load(call, rates=RATES)
    priced = price_trace(trace, RATES)
    assert all(not turn.tts and not turn.playback for turn in trace.turns)
    assert priced.stage_costs["tts"] == 0
    assert priced.stage_costs["llm"] > 0
    assert adjudicate(priced).label.value == "RESOLVED"


def test_agent_version_and_scenario_rules():
    call = _adapt(_retell_call([_utt("user", "Hi.", 0.0)], agent_version=12,
                               agent_id="agent-xyz"))
    assert call.agent_version == "retell/agent-xyz.v12"
    assert _adapt(_retell_call([_utt("user", "Hi.", 0.0)],
                               agent_name=None)).scenario == "unknown"
    assert _adapt(_retell_call([_utt("user", "Hi.", 0.0)],
                               agent_name="ACME Support!")).scenario == "acme_support"
    with pytest.raises(IngestError):
        _adapt(_retell_call([_utt("user", "Hi.", 0.0)], agent_version="3"))
    with pytest.raises(IngestError):
        _adapt(_retell_call([_utt("user", "Hi.", 0.0)], agent_id=""))


# --------------------------------------------------------------------------- #
# Timeline selection + word-timing fallback + skip rules                        #
# --------------------------------------------------------------------------- #

def test_transcript_object_fallback_used_when_no_tool_timeline():
    utterances = [_utt("agent", "Hello there.", 0.0),
                  _utt("user", "Hi, checking in.", 1.5),
                  _utt("agent", "All good then.", 3.5)]
    call = _adapt(_retell_call(utterances, with_tools=False))
    assert len(call.turns) == 2
    assert call.turns[0].llm.decision_kind.value == "route"
    assert call.turns[1].llm.decision_kind.value == "compose"


def test_with_tool_calls_preferred_over_transcript_object():
    timeline = [_utt("agent", "Timeline greeting.", 0.0),
                _utt("user", "Timeline question.", 1.5),
                _utt("agent", "Timeline answer.", 3.0)]
    decoy = [_utt("agent", "Decoy greeting.", 0.0)]
    call = _adapt(_retell_call(timeline, transcript_object=decoy))
    assert call.turns[0].llm.output_text == "Timeline greeting."
    assert len(call.turns) == 2


def test_wordless_utterances_fall_back_to_even_division_and_note_says_so():
    obj = _retell_call([
        {"role": "agent", "content": "Hello?"},
        {"role": "user", "content": "Hi."},
        {"role": "agent", "content": "Bye."},
    ])
    call = _adapt(obj)
    assert len(call.turns) == 2
    starts = [turn.start_ms for turn in call.turns]
    assert starts == sorted(starts)
    assert all(turn.end_ms > turn.start_ms for turn in call.turns)
    note = provider_info(obj, call)["note"]
    assert "evenly dividing the call duration" in note


def test_dtmf_sms_injected_skipped_and_node_transition_informational():
    base = [
        _utt("agent", "Hello, please press a key.", 0.0),
        {"role": "dtmf", "digit": "1"},
        _utt("user", "I pressed one.", 1.5),
        {"role": "sms", "content": "text me", "time_sec": 2.0},
        {"role": "injected", "content": "context", "time_sec": 2.5},
        {"role": "node_transition", "former_node_id": "n1",
         "former_node_name": "start", "new_node_id": "n2",
         "new_node_name": "collect"},
        _utt("agent", "Thanks, noted.", 3.0),
    ]
    skipped = _adapt(_retell_call(base))
    plain = _adapt(_retell_call([entry for entry in base
                                 if entry.get("role") in ("agent", "user")]))
    assert [t.llm.output_text for t in skipped.turns] == \
        [t.llm.output_text for t in plain.turns]
    assert len(skipped.turns) == 2


def test_transfer_target_speech_rides_caller_side_never_llm():
    obj = _retell_call([
        _utt("agent", "Connecting you now.", 0.0),
        {"role": "transfer_target", "content": "Hello, human here.",
         "words": _words("Hello, human here.", 2.0)},
    ], disconnection_reason="call_transfer")
    call = _adapt(obj)
    assert call.end_reason.value == "escalated"
    assert len(call.turns) == 2
    assert call.turns[1].asr is not None
    assert call.turns[1].asr.transcript == "Hello, human here."
    assert call.turns[1].llm is None


# --------------------------------------------------------------------------- #
# End-reason mapping + call_status gate, loud on unmapped                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("retell_reason", "expected"), [
    ("user_hangup", "caller_hangup"),
    ("agent_hangup", "agent_hangup"),
    ("call_transfer", "escalated"),
    ("transfer_bridged", "escalated"),
    ("inactivity", "timeout"),
    ("max_duration_reached", "timeout"),
    ("voicemail_reached", "error"),
    ("ivr_reached", "error"),
    ("dial_busy", "error"),
    ("dial_failed", "error"),
    ("dial_no_answer", "error"),
    ("telephony_provider_unavailable", "error"),
    ("error_llm_websocket_runtime", "error"),
    ("error_asr", "error"),
    ("error_retell", "error"),
    ("error_unknown", "error"),
    ("registered_call_timeout", "error"),
    ("transfer_cancelled", "error"),
    ("manual_stopped", "error"),
    ("call_take_over", "error"),
    ("no_valid_payment", "error"),
])
def test_end_reason_mapping(retell_reason, expected):
    assert map_end_reason(retell_reason) == expected
    call = _adapt(_retell_call([_utt("user", "Hi.", 0.0)],
                               disconnection_reason=retell_reason))
    assert call.end_reason.value == expected


def test_unmapped_end_reason_raises_with_value_and_path():
    with pytest.raises(IngestError) as excinfo:
        _adapt(_retell_call([_utt("user", "Hi.", 0.0)],
                            disconnection_reason="some-brand-new-retell-code"))
    assert "some-brand-new-retell-code" in str(excinfo.value)
    assert "disconnection_reason" in str(excinfo.value)


@pytest.mark.parametrize("status", ["registered", "not_connected", "ongoing", "error"])
def test_non_ended_call_status_raises(status):
    with pytest.raises(IngestError) as excinfo:
        _adapt(_retell_call([_utt("user", "Hi.", 0.0)], call_status=status))
    assert "call_status" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Tools: kind inference, override, effect resolution                            #
# --------------------------------------------------------------------------- #

def test_unknown_tool_kind_raises_with_name_and_override_path():
    obj = _retell_call([
        _utt("user", "Do the thing.", 0.0),
        _invoke("t1", "frobnicate_widget", {"x": 1}),
        _result("t1", '{"ok": true}'),
        _utt("agent", "Done.", 2.5),
    ])
    with pytest.raises(IngestError) as excinfo:
        _adapt(obj)
    assert "frobnicate_widget" in str(excinfo.value)
    fixed = _adapt(obj, tool_kinds={"frobnicate_widget": "mutation"})
    assert fixed.turns[0].tools[0].kind.value == "mutation"


def test_bad_tool_kind_override_raises():
    obj = _retell_call([
        _utt("user", "Do the thing.", 0.0),
        _invoke("t1", "lookup_order", {"x": 1}),
        _result("t1", '{"ok": true}'),
        _utt("agent", "Done.", 2.5),
    ])
    with pytest.raises(IngestError):
        _adapt(obj, tool_kinds={"lookup_order": "teleport"})


def test_contradictory_tool_result_raises():
    obj = _retell_call([
        _utt("user", "Pay my bill.", 0.0),
        _invoke("t1", "pay_bill", {"amount": 5}),
        _result("t1", '{"result": {"ok": true}, "error": "boom"}'),
        _utt("agent", "Done.", 2.5),
    ])
    with pytest.raises(IngestError) as excinfo:
        _adapt(obj)
    assert "pay_bill" in str(excinfo.value)


@pytest.mark.parametrize(("content", "successful", "effect", "status"), [
    ('{"status": "refunded"}', True, "committed", "ok"),
    ('{"status": "refunded"}', None, "committed", "ok"),
    ("queued -- confirmation pending", True, "pending", "ok"),
    ("card declined, unable to charge", True, "rejected", "ok"),
    ('{"error": "card declined"}', True, "rejected", "error"),
    ('{"status": "refunded"}', False, "rejected", "error"),
    (None, None, "unknown", "ok"),
])
def test_mutation_effect_resolution(content, successful, effect, status):
    entries = [_utt("user", "Refund me.", 0.0),
               _invoke("t1", "process_refund", {"order": "1"})]
    if content is not None:
        entries.append(_result("t1", content, successful)
                       if successful is not None
                       else _result("t1", content, omit_successful=True))
    entries.append(_utt("agent", "On it.", 2.5))
    tools = _adapt(_retell_call(entries)).turns[0].tools
    assert (tools[0].effect.value, tools[0].status.value) == (effect, status)


def test_lookup_reads_always_resolve_none():
    ok_obj = _retell_call([
        _utt("user", "Check it.", 0.0),
        _invoke("t1", "lookup_order", {"x": 1}),
        _result("t1", '{"ok": true}', successful=True),
        _utt("agent", "Checked.", 2.5),
    ])
    assert _adapt(ok_obj).turns[0].tools[0].effect.value == "none"
    err_obj = _retell_call([
        _utt("user", "Check it.", 0.0),
        _invoke("t1", "lookup_order", {"x": 1}),
        _result("t1", "boom", successful=False),
        _utt("agent", "Sorry.", 2.5),
    ])
    tool = _adapt(err_obj).turns[0].tools[0]
    assert (tool.effect.value, tool.status.value) == ("none", "error")


def test_bad_tool_arguments_raise():
    obj = _retell_call([
        _utt("user", "Book it.", 0.0),
        {"role": "tool_call_invocation", "tool_call_id": "t1",
         "name": "book_visit", "arguments": "{not json"},
        _utt("agent", "On it.", 2.5),
    ])
    with pytest.raises(IngestError):
        _adapt(obj)


# --------------------------------------------------------------------------- #
# Loud failures on missing/unmappable structure                                 #
# --------------------------------------------------------------------------- #

def test_missing_llm_identity_with_llm_turns_raises():
    obj = _retell_call([_utt("agent", "Hello?", 0.0), _utt("user", "Hi.", 1.5)])
    with pytest.raises(IngestError) as excinfo:
        from_retell(obj)
    assert "llm_identity" in str(excinfo.value)


def test_bad_llm_identity_raises():
    obj = _retell_call([_utt("agent", "Hello?", 0.0)])
    with pytest.raises(IngestError):
        from_retell(obj, llm_identity=("openai", ""))
    with pytest.raises(IngestError):
        from_retell(obj, llm_identity="openai/gpt-5-mini")


def test_caller_only_call_needs_neither_identity_nor_tokens():
    obj = _retell_call([_utt("user", "Hello? Is anyone there?", 0.0)])
    del obj["llm_token_usage"]
    call = from_retell(obj)
    assert all(turn.llm is None for turn in call.turns)
    assert call.turns[0].asr.transcript.startswith("Hello?")


def test_missing_token_totals_raise():
    obj = _retell_call([_utt("agent", "Hello?", 0.0), _utt("user", "Hi.", 1.5)])
    del obj["llm_token_usage"]
    with pytest.raises(IngestError) as excinfo:
        _adapt(obj)
    assert "llm_token_usage" in str(excinfo.value)


def test_empty_token_values_raise():
    obj = _retell_call([_utt("agent", "Hello?", 0.0), _utt("user", "Hi.", 1.5)],
                       llm_token_usage={"values": [], "average": 0.0,
                                        "num_requests": 0})
    with pytest.raises(IngestError) as excinfo:
        _adapt(obj)
    assert "llm_token_usage" in str(excinfo.value)


def test_unknown_entry_role_raises():
    obj = _retell_call([{"role": "hologram", "content": "boo",
                         "words": _words("boo", 0.0)}])
    with pytest.raises(IngestError) as excinfo:
        _adapt(obj)
    assert "hologram" in str(excinfo.value)


def test_empty_timeline_raises():
    with pytest.raises(IngestError):
        _adapt(_retell_call([], with_tools=False, transcript_object=[]))
    with pytest.raises(IngestError):
        _adapt(_retell_call([{"role": "dtmf", "digit": "1"}], with_tools=True,
                            transcript_object=[{"role": "dtmf", "digit": "1"}]))


def test_native_ingest_shape_is_rejected_as_retell():
    with pytest.raises(IngestError) as excinfo:
        from_retell({"id": "native-001", "scenario": "refund"})
    assert "call_id" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# from_retell_export shapes                                                     #
# --------------------------------------------------------------------------- #

def test_export_accepts_single_list_and_wrappers():
    one = _retell_call([_utt("user", "Hi.", 0.0)], call_id="retell-a")
    two = _retell_call([_utt("user", "Yo.", 0.0)], call_id="retell-b")
    assert [c.id for c in from_retell_export(one, llm_identity=LLM)] == ["retell-a"]
    assert [c.id for c in from_retell_export([one, two], llm_identity=LLM)] == \
        ["retell-a", "retell-b"]
    assert [c.id for c in from_retell_export({"calls": [one, two]},
                                             llm_identity=LLM)] == ["retell-a", "retell-b"]
    assert [c.id for c in from_retell_export({"results": [one]},
                                             llm_identity=LLM)] == ["retell-a"]
    assert [c.id for c in from_retell_export({"data": [one]},
                                             llm_identity=LLM)] == ["retell-a"]
    with pytest.raises(IngestError):
        from_retell_export({"nope": []}, llm_identity=LLM)
    with pytest.raises(IngestError):
        from_retell_export([], llm_identity=LLM)


def test_export_path_matches_direct_path():
    obj = _golden_call()
    assert from_retell_export(copy.deepcopy(obj), llm_identity=LLM)[0] == _adapt(obj)


# --------------------------------------------------------------------------- #
# Honesty: acoustics absent, decision_kind flagged, D1 gated                    #
# --------------------------------------------------------------------------- #

def test_absent_acoustics_means_d6_d7_d8_absent():
    call = _adapt(SAMPLE)
    report = run_call(call, RATES, BASELINES, provider=_prov(SAMPLE, call, sample=True))
    for class_id in ("6", "7", "8"):
        assert report["coverage"][class_id]["status"] == "absent"
    assert not any(f["class_id"] in (6, 7, 8) for f in report["findings"])
    assert report["source"] == "Retell export (synthetic schema-conformant example)"


def test_inferred_kinds_are_flagged_in_provenance():
    call = _adapt(SAMPLE)
    info = provider_info(SAMPLE, call, sample=True)
    assert set(info) == {"source", "note", "inferred_decision_turns"}
    assert info["source"] == "Retell export (synthetic schema-conformant example)"
    assert info["inferred_decision_turns"] == [0, 1, 2, 3]
    assert "inferred" in info["note"] and "D1 excluded" in info["note"]
    assert "D6/D7/D8 ABSENT" in info["note"]
    assert "no prompt/completion split" in info["note"]


def test_inferred_decision_turns_covers_every_llm_turn():
    call = _adapt(SAMPLE)
    assert inferred_decision_turns(call) == {0, 1, 2, 3}
    assert describe_coverage(call, inferred_decision_turns=set())[1]["status"] == "present"


def test_d1_never_reports_inferred_spans_as_measured():
    """Load-bearing honesty test: raw detect() DOES fire D1 on the probe
    (frontier gpt-5 route, short output), but the pipeline drops it and marks
    D1 ABSENT."""
    obj = _route_probe_call()
    call = from_retell(obj, llm_identity=("openai", "gpt-5"))
    assert call.turns[0].llm.decision_kind.value == "route"
    priced = price_trace(load(call, rates=RATES), RATES)
    raw_classes = {f.class_id for f in detect(priced, adjudicate(priced), BASELINES)}
    assert 1 in raw_classes  # the exclusion does real work, not vacuous
    report = run_call(call, RATES, BASELINES,
                      provider={call.id: provider_info(obj, call)})
    assert report["coverage"]["1"]["status"] == "absent"
    assert "no data for this input" in report["coverage"]["1"]["reason"]
    assert not any(f["class_id"] == 1 for f in report["findings"])
    assert 1 in report["excluded_absent_classes"]


def test_partial_inference_filters_only_inferred_turns():
    obj = _route_probe_call()
    call = from_retell(obj, llm_identity=("openai", "gpt-5"))
    # A record naming an unrelated turn: D1 stays PRESENT, finding kept.
    report = run_call(call, RATES, BASELINES,
                      provider={call.id: {"source": "x", "note": "x",
                                          "inferred_decision_turns": [7]}})
    assert report["coverage"]["1"]["status"] == "present"
    assert any(f["class_id"] == 1 for f in report["findings"])
    # The same record naming turn 0: finding dropped, class still PRESENT
    # (turn 1 carries a measured-by-assumption kind).
    report = run_call(call, RATES, BASELINES,
                      provider={call.id: {"source": "x", "note": "x",
                                          "inferred_decision_turns": [0]}})
    assert report["coverage"]["1"]["status"] == "present"
    assert not any(f["class_id"] == 1 for f in report["findings"])


def test_margin_excludes_fully_inferred_calls():
    obj = _route_probe_call()
    call = from_retell(obj, llm_identity=("openai", "gpt-5"))
    artifact, details = run_calls([call], RATES, BASELINES, label="t",
                                  sample=False,
                                  provider={call.id: provider_info(obj, call)})
    assert artifact["fleet"]["recoverable_margin_pct"] == 0.0
    assert "excluded" in artifact["fleet"]["_provenance"]["note"]
    assert "source: Retell export" in artifact["provenance"]
    row = artifact["calls"][0]
    assert set(row) == {"id", "scenario_id", "cost_usd", "verdict",
                        "end_reason", "n_turns", "top_waste", "quality", "detail"}
    detail = details[row["detail"]]
    assert detail["_provenance"]["source"] == "Retell export"


# --------------------------------------------------------------------------- #
# Telephony mapping                                                             #
# --------------------------------------------------------------------------- #

def test_web_call_omits_telephony_and_marks_d8_absent():
    obj = _retell_call([_utt("user", "Hi.", 0.0)], call_type="web_call")
    call = _adapt(obj)
    assert call.telephony is None
    report = run_call(call, RATES, BASELINES, provider=_prov(obj, call))
    assert report["coverage"]["8"]["status"] == "absent"


def test_outbound_direction_passes_through():
    obj = _retell_call([_utt("user", "Hi.", 0.0)], direction="outbound")
    assert _adapt(obj).telephony.direction.value == "outbound"


def test_unknown_call_type_raises():
    with pytest.raises(IngestError) as excinfo:
        _adapt(_retell_call([_utt("user", "Hi.", 0.0)], call_type="sip_call"))
    assert "call_type" in str(excinfo.value)


def test_telephony_provider_param_passes_through_and_fails_loud_without_rate():
    obj = _retell_call([_utt("user", "Hi.", 0.0)])
    assert _adapt(obj).telephony.provider == "twilio"  # documented default
    call = _adapt(obj, telephony_provider="vonage")
    assert call.telephony.provider == "vonage"
    with pytest.raises(IngestError) as excinfo:
        load(call, rates=RATES)
    message = str(excinfo.value)
    assert "vonage/pstn_inbound" in message
    assert "pricing/rates.yaml" in message  # template pointer


def test_no_len_text_standin_anywhere():
    """No adapter output may smuggle text length in as a measured count."""
    call = _adapt(SAMPLE)
    dump = call.model_dump()
    for turn in dump["turns"]:
        if turn.get("tts"):
            assert turn["tts"]["chars_synthesized"] is None
            assert turn["tts"]["chars_played"] is None
