"""Vapi adapter tests (PRD 02): mapping, loud failure, honesty boundaries.

Conventions mirror test_load.py / test_pipeline.py: small inline Vapi
exports plus the committed ``sample/vapi-export.sample.json`` as the golden
fixture. Every test pins an honesty invariant -- inferred labels flagged,
absent data ABSENT (never zeroed), unmappable input loud.
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
    from_vapi,
    from_vapi_export,
    load,
    parse_call,
    provider_info,
    run_call,
    run_calls,
)

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate({"per_intent": {
    "billing_assistant": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
    "order_status": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
}})
SAMPLE_PATH = ROOT / "packages" / "ingest" / "sample" / "vapi-export.sample.json"
SAMPLE = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

BASE = 1789203731000  # epoch ms of the sample's startedAt


def _speech(role, text, start_s, dur_s, **extra):
    time = BASE + int(start_s * 1000)
    return {"role": role, "message": text, "time": time,
            "endTime": time + int(dur_s * 1000),
            "secondsFromStart": start_s, "duration": int(dur_s * 1000), **extra}


def _tool_call(call_id, name, args, start_s):
    time = BASE + int(start_s * 1000)
    return {"role": "tool_calls", "message": f"Calling {name}.",
            "time": time, "endTime": time + 400, "secondsFromStart": start_s,
            "toolCalls": [{"id": call_id, "name": name, "parameters": args}]}


def _tool_result(call_id, name, start_s, *, result=None, error=None):
    time = BASE + int(start_s * 1000)
    msg = {"role": "tool_call_result", "toolCallId": call_id, "name": name,
           "time": time, "endTime": time + 400, "secondsFromStart": start_s}
    if result is not None:
        msg["result"] = result
    if error is not None:
        msg["error"] = error
    return msg


def _vapi_call(messages, **overrides):
    call = {
        "id": "vapi-test-001",
        "type": "inboundPhoneCall",
        "status": "ended",
        "endedReason": "customer-ended-call",
        "startedAt": "2026-09-12T09:02:11.000Z",
        "endedAt": "2026-09-12T09:02:41.000Z",
        "costBreakdown": {"transport": 0.004, "stt": 0.003, "llm": 0.012,
                          "tts": 0.018, "vapi": 0.05, "total": 0.087,
                          "llmPromptTokens": 900, "llmCompletionTokens": 30,
                          "llmCachedPromptTokens": 90, "ttsCharacters": 120},
        "phoneCallProvider": "twilio",
        "assistant": {"name": "Billing Assistant",
                      "model": {"provider": "openai", "model": "gpt-5-mini"}},
        "artifact": {"messages": messages},
    }
    call.update(overrides)
    return call


def _route_probe_call():
    """Three-message export whose opening route turn WOULD fire D1 (frontier
    gpt-5, short output) if its decision_kind were agent-emitted. Two LLM
    turns so partial-inference gating has something to split."""
    return _vapi_call(
        [_speech("bot", "How can I help?", 0.0, 1.0),
         _speech("user", "Where is my order?", 1.5, 1.5),
         _speech("bot", "One moment, checking now.", 3.5, 1.0)],
        id="vapi-d1-probe",
        assistant={"name": "Order Status",
                   "model": {"provider": "openai", "model": "gpt-5"}},
    )


def _prov(call_obj, adapted=None, **kwargs):
    adapted = adapted if adapted is not None else from_vapi(call_obj)
    return {adapted.id: provider_info(call_obj, adapted, **kwargs)}


# --------------------------------------------------------------------------- #
# Golden sample mapping (PRD §8: field-level assertions)                       #
# --------------------------------------------------------------------------- #

def test_sample_file_is_labeled_synthetic():
    assert SAMPLE["sample"] is True
    assert "NOT real customer traffic" in SAMPLE["_note"]


def test_sample_maps_to_expected_ingest_call():
    call = from_vapi(SAMPLE)
    assert call.id == "7f3b2c1a-9e4d-4f6a-b8c2-1a2b3c4d5e6f"
    assert call.scenario == "billing_assistant"
    assert call.end_reason.value == "caller_hangup"
    assert call.agent_version == "vapi/asst-billing-synthetic"
    assert call.telephony is not None
    assert call.telephony.billable_seconds == 30
    assert len(call.turns) == 4

    opening, middle, mutation, close = call.turns
    # Turn grouping: greeting-first turn, then one turn per caller utterance.
    assert opening.asr is None and opening.speaker_first.value == "agent"
    assert middle.asr is not None and middle.asr.transcript.startswith("Hi, I was charged twice")
    assert mutation.asr is not None and mutation.asr.transcript == "Yes, please fix it."
    assert close.asr is not None and "Thanks, bye" in close.asr.transcript

    # §5 inference rules: route-first, tool_select-on-mutation, compose.
    assert opening.llm.decision_kind.value == "route"
    assert opening.llm.decision == "billing_assistant"
    assert opening.llm.decision_candidates == ["billing_assistant", "other"]
    assert middle.llm.decision_kind.value == "compose"
    assert mutation.llm.decision_kind.value == "tool_select"
    assert mutation.llm.decision == "adjust_billing"
    assert close.llm.decision_kind.value == "compose"

    # output_text is the agent's own message -- never empty, never tool text.
    assert opening.llm.output_text.startswith("Hi, thanks for calling")
    assert "refunded the duplicate" in mutation.llm.output_text

    # Tools: lookup reads effect=none; committed mutation resolves committed.
    lookup = middle.tools[0]
    assert (lookup.name, lookup.kind.value, lookup.effect.value) == (
        "lookup_invoices", "lookup", "none")
    adjust = mutation.tools[0]
    assert (adjust.name, adjust.kind.value, adjust.effect.value,
            adjust.status.value) == ("adjust_billing", "mutation", "committed", "ok")

    # Tokens: exact-sum even split of the call totals across 4 LLM turns.
    assert sum(t.llm.input_tokens for t in call.turns) == 3900 - 390
    assert sum(t.llm.output_tokens for t in call.turns) == 150
    assert sum(t.llm.cache_read_tokens for t in call.turns) == 390

    # TTS text rides along but char counts are absent (G2: no stand-in).
    assert all(t.tts is not None and t.tts.text for t in call.turns)
    assert all(t.tts.chars_synthesized is None and t.tts.chars_played is None
               for t in call.turns)


def test_sample_loads_and_prices_with_no_acoustic_spans():
    call = from_vapi(SAMPLE)
    trace = load(call, rates=RATES)
    priced = price_trace(trace, RATES)
    assert all(not turn.tts and not turn.playback for turn in trace.turns)
    assert priced.stage_costs["tts"] == 0
    assert priced.stage_costs["llm"] > 0
    assert adjudicate(priced).label.value == "RESOLVED"


# --------------------------------------------------------------------------- #
# P0: enum + reason mapping, loud on unmapped                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("vapi_reason", "expected"), [
    ("customer-ended-call", "caller_hangup"),
    ("customer-ended-call-during-transfer", "caller_hangup"),
    ("assistant-ended-call", "agent_hangup"),
    ("assistant-ended-call-after-message-spoken", "agent_hangup"),
    ("assistant-said-end-call-phrase", "agent_hangup"),
    ("assistant-forwarded-call", "escalated"),
    ("exceeded-max-duration", "timeout"),
    ("silence-timed-out", "timeout"),
    ("pipeline-error-openai-llm-failed", "error"),
    ("call.start.error-subscription-insufficient-credits", "error"),
    ("call.in-progress.error-vapifault-worker-died", "error"),
    ("customer-did-not-answer", "error"),
    ("vonage-failed-to-connect-call", "error"),
    ("worker-shutdown", "error"),
])
def test_end_reason_mapping(vapi_reason, expected):
    call = from_vapi(_vapi_call(
        [_speech("bot", "Hello?", 0.0, 1.0), _speech("user", "Hello.", 1.5, 1.0)],
        endedReason=vapi_reason))
    assert call.end_reason.value == expected


def test_unmapped_end_reason_raises_with_value():
    with pytest.raises(IngestError) as excinfo:
        from_vapi(_vapi_call(
            [_speech("bot", "Hello?", 0.0, 1.0)],
            endedReason="some-brand-new-vapi-code"))
    assert "some-brand-new-vapi-code" in str(excinfo.value)
    assert "endedReason" in str(excinfo.value)


def test_unknown_tool_kind_raises_with_name_and_override_path():
    obj = _vapi_call([
        _speech("user", "Do the thing.", 0.0, 1.0),
        _tool_call("t1", "frobnicate_widget", {"x": 1}, 1.5),
        _tool_result("t1", "frobnicate_widget", 2.0, result='{"ok": true}'),
        _speech("bot", "Done.", 2.5, 1.0),
    ])
    with pytest.raises(IngestError) as excinfo:
        from_vapi(obj)
    assert "frobnicate_widget" in str(excinfo.value)
    fixed = from_vapi(obj, tool_kinds={"frobnicate_widget": "mutation"})
    assert fixed.turns[0].tools[0].kind.value == "mutation"


def test_bad_tool_kind_override_raises():
    obj = _vapi_call([
        _speech("user", "Do the thing.", 0.0, 1.0),
        _tool_call("t1", "lookup_order", {"x": 1}, 1.5),
        _tool_result("t1", "lookup_order", 2.0, result='{"ok": true}'),
        _speech("bot", "Done.", 2.5, 1.0),
    ])
    with pytest.raises(IngestError):
        from_vapi(obj, tool_kinds={"lookup_order": "teleport"})


def test_contradictory_tool_result_raises():
    obj = _vapi_call([
        _speech("user", "Pay my bill.", 0.0, 1.0),
        _tool_call("t1", "pay_bill", {"amount": 5}, 1.5),
        _tool_result("t1", "pay_bill", 2.0, result='{"ok": true}', error="boom"),
        _speech("bot", "Done.", 2.5, 1.0),
    ])
    with pytest.raises(IngestError) as excinfo:
        from_vapi(obj)
    assert "pay_bill" in str(excinfo.value)


@pytest.mark.parametrize(("result", "effect", "status"), [
    ('{"status": "refunded"}', "committed", "ok"),
    ("queued -- confirmation pending", "pending", "ok"),
    (None, "unknown", "ok"),
])
def test_mutation_effect_resolution(result, effect, status):
    kwargs = {"result": result} if result is not None else {}
    obj = _vapi_call([
        _speech("user", "Refund me.", 0.0, 1.0),
        _tool_call("t1", "process_refund", {"order": "1"}, 1.5),
        _tool_result("t1", "process_refund", 2.0, **kwargs),
        _speech("bot", "On it.", 2.5, 1.0),
    ])
    tools = from_vapi(obj).turns[0].tools
    assert (tools[0].effect.value, tools[0].status.value) == (effect, status)


def test_mutation_error_result_is_rejected():
    obj = _vapi_call([
        _speech("user", "Refund me.", 0.0, 1.0),
        _tool_call("t1", "process_refund", {"order": "1"}, 1.5),
        _tool_result("t1", "process_refund", 2.0, error="card declined"),
        _speech("bot", "Sorry.", 2.5, 1.0),
    ])
    tools = from_vapi(obj).turns[0].tools
    assert (tools[0].effect.value, tools[0].status.value) == ("rejected", "error")


# --------------------------------------------------------------------------- #
# Loud failures on missing/unmappable structure                                #
# --------------------------------------------------------------------------- #

def test_missing_cost_breakdown_with_llm_turns_raises():
    obj = _vapi_call([_speech("bot", "Hello?", 0.0, 1.0),
                      _speech("user", "Hi.", 1.5, 1.0)])
    del obj["costBreakdown"]
    with pytest.raises(IngestError) as excinfo:
        from_vapi(obj)
    assert "costBreakdown" in str(excinfo.value)


def test_missing_token_totals_raise():
    obj = _vapi_call([_speech("bot", "Hello?", 0.0, 1.0),
                      _speech("user", "Hi.", 1.5, 1.0)])
    del obj["costBreakdown"]["llmPromptTokens"]
    with pytest.raises(IngestError) as excinfo:
        from_vapi(obj)
    assert "costBreakdown" in str(excinfo.value)


def test_unknown_message_role_raises():
    obj = _vapi_call([{"role": "hologram", "message": "boo",
                       "time": BASE, "endTime": BASE + 100, "secondsFromStart": 0.0}])
    with pytest.raises(IngestError) as excinfo:
        from_vapi(obj)
    assert "hologram" in str(excinfo.value)


def test_empty_timeline_raises():
    with pytest.raises(IngestError):
        from_vapi(_vapi_call([], id="vapi-empty"))


def test_native_ingest_shape_is_rejected_as_vapi():
    with pytest.raises(IngestError):
        from_vapi({"id": "native-001", "scenario": "refund"})


# --------------------------------------------------------------------------- #
# from_vapi_export shapes                                                      #
# --------------------------------------------------------------------------- #

def test_export_accepts_single_list_and_wrappers():
    one = _vapi_call([_speech("user", "Hi.", 0.0, 1.0)], id="vapi-a")
    two = _vapi_call([_speech("user", "Yo.", 0.0, 1.0)], id="vapi-b")
    assert [c.id for c in from_vapi_export(one)] == ["vapi-a"]
    assert [c.id for c in from_vapi_export([one, two])] == ["vapi-a", "vapi-b"]
    assert [c.id for c in from_vapi_export({"calls": [one, two]})] == ["vapi-a", "vapi-b"]
    assert [c.id for c in from_vapi_export({"results": [one]})] == ["vapi-a"]
    assert [c.id for c in from_vapi_export({"data": [one]})] == ["vapi-a"]
    with pytest.raises(IngestError):
        from_vapi_export({"nope": []})
    with pytest.raises(IngestError):
        from_vapi_export([])


# --------------------------------------------------------------------------- #
# Honesty: acoustics absent, decision_kind flagged, D1 gated                   #
# --------------------------------------------------------------------------- #

def test_absent_acoustics_means_d6_d7_d8_absent():
    call = from_vapi(SAMPLE)
    report = run_call(call, RATES, BASELINES, provider=_prov(SAMPLE, call, sample=True))
    for class_id in ("6", "7", "8"):
        assert report["coverage"][class_id]["status"] == "absent"
    assert not any(f["class_id"] in (6, 7, 8) for f in report["findings"])
    assert report["source"] == "Vapi export (synthetic schema-conformant example)"


def test_inferred_kinds_are_flagged_in_provenance():
    call = from_vapi(SAMPLE)
    info = provider_info(SAMPLE, call, sample=True)
    assert info["source"] == "Vapi export (synthetic schema-conformant example)"
    assert info["inferred_decision_turns"] == [0, 1, 2, 3]
    assert "inferred" in info["note"] and "D1 excluded" in info["note"]


def test_d1_never_reports_inferred_spans_as_measured():
    """Load-bearing §5 test: raw detect() DOES fire D1 on the probe (frontier
    route, short output), but the pipeline drops it and marks D1 ABSENT."""
    obj = _route_probe_call()
    call = from_vapi(obj)
    assert call.turns[0].llm.decision_kind.value == "route"
    priced = price_trace(load(call, rates=RATES), RATES)
    raw_classes = {f.class_id for f in detect(priced, adjudicate(priced), BASELINES)}
    assert 1 in raw_classes  # the exclusion does real work, not vacuous
    report = run_call(call, RATES, BASELINES, provider=_prov(obj, call))
    assert report["coverage"]["1"]["status"] == "absent"
    assert "no data for this input" in report["coverage"]["1"]["reason"]
    assert not any(f["class_id"] == 1 for f in report["findings"])
    assert 1 in report["excluded_absent_classes"]


def test_partial_inference_filters_only_inferred_turns():
    obj = _route_probe_call()
    call = from_vapi(obj)
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
    call = from_vapi(obj)
    artifact, details = run_calls([call], RATES, BASELINES, label="t",
                                  sample=False, provider=_prov(obj, call))
    assert artifact["fleet"]["recoverable_margin_pct"] == 0.0
    assert "excluded" in artifact["fleet"]["_provenance"]["note"]
    assert "source: Vapi export" in artifact["provenance"]
    row = artifact["calls"][0]
    assert set(row) == {"id", "scenario_id", "cost_usd", "verdict",
                        "end_reason", "n_turns", "top_waste", "detail"}
    detail = details[row["detail"]]
    assert detail["_provenance"]["source"] == "Vapi export"


def test_native_provenance_strings_unchanged_without_provider():
    """Backward-compat pin: the native path's envelope strings are untouched."""
    obj = {"id": "native-001", "scenario": "order_status",
           "started": "2026-09-04T09:00:00Z", "ended": "2026-09-04T09:01:00Z",
           "end_reason": "caller_hangup",
           "telephony": {"provider": "twilio", "direction": "inbound",
                         "billable_seconds": 60},
           "turns": [{"start_ms": 0, "end_ms": 5000,
                      "asr": {"transcript": "Hi.", "start_ms": 200, "duration_ms": 800},
                      "llm": {"model": "gpt-5-mini", "input_tokens": 700,
                              "output_tokens": 12, "decision_kind": "compose",
                              "decision": "greet", "output_text": "Hello!",
                              "start_ms": 1200, "duration_ms": 600}}]}
    artifact, _ = run_calls([obj], RATES, BASELINES, label="test", sample=True)
    assert artifact["provenance"].startswith(
        "turnstile_ingest report over the bundled 7-call SAMPLE")
    assert "source:" not in artifact["provenance"]
    report = run_call(obj, RATES, BASELINES)
    assert report["source"] is None
    assert report["coverage"]["1"]["status"] == "present"


# --------------------------------------------------------------------------- #
# Telephony / misc mapping                                                     #
# --------------------------------------------------------------------------- #

def test_web_call_omits_telephony_and_marks_d8_absent():
    obj = _vapi_call([_speech("user", "Hi.", 0.0, 1.0)], type="webCall")
    call = from_vapi(obj)
    assert call.telephony is None
    report = run_call(call, RATES, BASELINES, provider=_prov(obj, call))
    assert report["coverage"]["8"]["status"] == "absent"


def test_outbound_direction_passes_through():
    obj = _vapi_call([_speech("user", "Hi.", 0.0, 1.0)], type="outboundPhoneCall")
    assert from_vapi(obj).telephony.direction.value == "outbound"


def test_cli_headline_reports_margin_excluded_count(capsys, tmp_path):
    """The excluded count comes from run_calls (coverage_summary), not a
    recompute: vapi sample prints it, native sample does not."""
    from turnstile_ingest.__main__ import main

    out = tmp_path / "vapi-out"
    assert main(["--provider", "vapi", "--out", str(out)]) == 0
    vapi_stdout = capsys.readouterr().out
    assert "margin over 0/1 calls -- 1 provider-adapted call(s) excluded" in vapi_stdout
    artifact = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert artifact["coverage_summary"]["margin_excluded"] == 1

    native = tmp_path / "native-out"
    assert main(["--sample", "--out", str(native)]) == 0
    native_stdout = capsys.readouterr().out
    assert "excluded" not in native_stdout
    native_artifact = json.loads((native / "data.json").read_text(encoding="utf-8"))
    assert native_artifact["coverage_summary"]["margin_excluded"] == 0


def test_cli_provider_vapi_end_to_end(tmp_path):
    from turnstile_ingest.__main__ import main
    out = tmp_path / "out"
    assert main(["--provider", "vapi", "--in", str(SAMPLE_PATH),
                 "--out", str(out)]) == 0
    artifact = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert artifact["n"] == 1 and artifact["sample"] is True
    assert "source: Vapi export (synthetic schema-conformant example)" in artifact["provenance"]
    for key in ("label", "n", "note", "provenance", "fleet",
                "coverage_summary", "calls", "findings"):
        assert key in artifact
    row = artifact["calls"][0]
    detail = json.loads((out / row["detail"]).read_text(encoding="utf-8"))
    assert detail["conv_cost"] == row["cost_usd"]
    assert detail["_provenance"]["coverage"]["1"]["status"] == "absent"


def test_mixed_native_and_vapi_fleet_keeps_native_margin():
    """A mixed fleet still prices D1 margin over the measured (native) leg."""
    native = {"id": "native-001", "scenario": "order_status",
              "started": "2026-09-04T09:00:00Z", "ended": "2026-09-04T09:01:00Z",
              "end_reason": "caller_hangup",
              "telephony": {"provider": "twilio", "direction": "inbound",
                            "billable_seconds": 60},
              "turns": [{"start_ms": 0, "end_ms": 5000,
                         "asr": {"transcript": "Hi.", "start_ms": 200, "duration_ms": 800},
                         "llm": {"model": "gpt-5", "input_tokens": 900,
                                 "output_tokens": 10, "decision_kind": "route",
                                 "decision": "order_status",
                                 "output_text": "Checking.",
                                 "start_ms": 1200, "duration_ms": 600}}]}
    obj = _route_probe_call()
    vapi_call = from_vapi(obj)
    native_call = parse_call(native)
    artifact, _ = run_calls([native_call, vapi_call], RATES, BASELINES,
                            label="mixed", sample=False,
                            provider=_prov(obj, vapi_call))
    assert artifact["coverage_summary"]["calls_with_data_per_class"].get("1") == 1
    assert "1 provider-adapted call(s)" in artifact["fleet"]["_provenance"]["note"]


def test_no_len_text_standin_anywhere():
    """No adapter output may smuggle text length in as a measured count."""
    call = from_vapi(SAMPLE)
    dump = call.model_dump()
    for turn in dump["turns"]:
        if turn.get("tts"):
            assert turn["tts"]["chars_synthesized"] is None
            assert turn["tts"]["chars_played"] is None
    copied = copy.deepcopy(SAMPLE)
    assert from_vapi_export(copied)[0] == call  # export path == direct path


# --------------------------------------------------------------------------- #
# Vapi-leg rate template (02 improvement): uncomment-and-go, loud pointer      #
# --------------------------------------------------------------------------- #

TEMPLATE_KEYS = (
    "twilio/pstn_outbound",
    "vonage/pstn_inbound",
    "vonage/pstn_outbound",
    "telnyx/pstn_inbound",
    "telnyx/pstn_outbound",
)


def test_unknown_telephony_key_names_key_and_template():
    obj = _vapi_call([_speech("user", "Hi.", 0.0, 1.0)],
                     phoneCallProvider="vonage")
    call = from_vapi(obj)  # mapping passes the provider through untouched
    with pytest.raises(IngestError) as excinfo:
        load(call, rates=RATES)
    message = str(excinfo.value)
    assert "vonage/pstn_inbound" in message
    assert "pricing/rates.yaml" in message  # template pointer


def test_commented_template_rows_load_once_uncommented(tmp_path):
    """The template is mechanical: stripping one `#` per row line yields
    valid YAML that loads the expected telephony keys."""
    import re

    text = (ROOT / "pricing" / "rates.yaml").read_text(encoding="utf-8")
    uncommented = [
        line.replace("  #", "  ", 1) if re.match(r"^  #[^ ]", line) else line
        for line in text.splitlines()
    ]
    assert uncommented != text.splitlines()  # template rows exist
    candidate = tmp_path / "rates.yaml"
    candidate.write_text("\n".join(uncommented) + "\n", encoding="utf-8")
    table = load_rates(candidate)
    for key in TEMPLATE_KEYS:
        assert key in table.telephony, key
    # And the live file still prices without them (rows stay commented).
    assert all(key not in RATES.telephony for key in TEMPLATE_KEYS)
