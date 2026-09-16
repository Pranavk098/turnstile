"""Track D — Retell honesty gates (Day-2 P0 #4, Retell-flavored ports of the Vapi gates).

Skip-safe by construction: Tracks A (adapter) and B (CLI + committed sample)
run in parallel and may not have merged yet. Every test that needs
``turnstile_ingest.providers.retell`` goes through :func:`_retell` (a
``pytest.importorskip`` guard), and every test that reads Track B's committed
sample goes through :func:`_retell_sample` (``pytest.skip`` when the file is
absent). Tests that only need the already-merged pipeline entry points
(``run_call`` / ``run_calls`` + a Retell-flavored provider record) RUN now and
prove the generic gates Retell records will flow through post-merge.

Gate map (each test header-comments its gate; Track A owns the adapter unit
tests in ``test_retell.py`` — where coverage would duplicate, the deferral
target is named):

* Gate 1 (golden fixture -> expected IngestCall):
  ``test_retell_inline_probe_maps_to_expected_ingest_call`` (inline builder,
  needs Track A adapter; Track B's committed-sample twin is
  ``test_retell_committed_sample_maps_to_expected_ingest_call``).
  Defers to Track A ``test_retell.py::test_sample_maps_to_expected_ingest_call``
  for the sample-shape pins; this file covers the inline-probe stratum.
* Gate 2 (unmapped enum -> loud error):
  ``test_retell_unmapped_disconnection_reason_raises`` +
  ``test_retell_ongoing_call_status_raises`` (both need Track A).
  Defers to Track A ``test_retell.py::test_unmapped_end_reason_raises...`` for
  the table pins; this file covers the ``disconnection_reason`` path name and
  the non-ended ``call_status`` rejection.
* Gate 3 (acoustic absence -> D6/D7/D8 ABSENT):
  ``test_retell_probe_acoustic_absence_marks_d6_d7_d8_absent`` (runs NOW) +
  ``test_retell_probe_absence_excludes_real_raw_d6_findings`` (load-bearing D6,
  runs NOW; follows ``test_pipeline.py::
  test_absence_excludes_real_raw_findings_instead_of_zeroing``).
* Gate 4 (inferred decision_kind -> never measured D1):
  ``test_retell_probe_inferred_decision_kind_never_measured_d1``
  (load-bearing, runs NOW; mirrors ``test_vapi.py::
  test_d1_never_reports_inferred_spans_as_measured``) +
  ``test_retell_probe_partial_inference_filters_only_inferred_turns`` (runs NOW)
  + ``test_mixed_native_and_retell_fleet_margin_excluded_with_headline``
  (runs NOW; mirrors ``test_vapi.py::
  test_mixed_native_and_vapi_fleet_keeps_native_margin``).
  Defers single-call D1 pins to Track A ``test_retell.py`` where duplicated;
  this file owns the mixed-fleet margin stratum.

P1 #6 (D9 tier-2 forwarded-call rule): VERIFY-OR-DEFER, never a rebuild — see
the footer comment for the defer verdict + dataset evidence.

Every test is PURE ($0: no network, no keys, no opt-in spend flag anywhere in
this file) so CI runs the passing stratum and skips the rest.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from turnstile_detectors import detect
from turnstile_pricing import price_trace
from turnstile_schema import Baselines, load_rates
from turnstile_verdict import adjudicate
from turnstile_ingest import (
    IngestError,
    load,
    parse_call,
    run_call,
    run_calls,
)

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate({"per_intent": {
    "billing_assistant": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
    "order_status": {"p50_turns": 5.0, "p75_turns": 7.25, "mean_cost_per_turn": 0.0028},
}})
# Track B's committed sample (absent until B merges -> tests using it skip).
RETELL_SAMPLE_PATH = ROOT / "packages" / "ingest" / "sample" / "retell-export.sample.json"


def _retell():
    """The Track A adapter module, or SKIP when A hasn't merged yet."""
    return pytest.importorskip(
        "turnstile_ingest.providers.retell",
        reason="Track A providers/retell.py not merged yet",
    )


def _retell_sample():
    """Track B's committed Retell sample object, or SKIP when B hasn't merged."""
    if not RETELL_SAMPLE_PATH.exists():
        pytest.skip(f"Track B sample not merged yet: {RETELL_SAMPLE_PATH.name} absent")
    return json.loads(RETELL_SAMPLE_PATH.read_text(encoding="utf-8"))


def _from_retell(retell, obj, **kwargs):
    """Call ``from_retell`` tolerantly across the parallel-track contract.

    ``00-readme.md`` §1 pins ``from_retell(call_obj, *, tool_kinds=None)``;
    Track A additionally requires caller-supplied ``llm_identity=(system,
    model)`` (Retell names no model — inventing one would be fabrication).
    Pass it when the merged signature accepts it.
    """
    params = inspect.signature(retell.from_retell).parameters
    if "llm_identity" in params and "llm_identity" not in kwargs:
        kwargs["llm_identity"] = ("openai", "gpt-5-mini")
    return retell.from_retell(obj, **kwargs)


def _from_retell_export(retell, obj, **kwargs):
    """``from_retell_export`` with the same ``llm_identity`` tolerance."""
    params = inspect.signature(retell.from_retell_export).parameters
    if "llm_identity" in params and "llm_identity" not in kwargs:
        kwargs["llm_identity"] = ("openai", "gpt-5-mini")
    return retell.from_retell_export(obj, **kwargs)


# --------------------------------------------------------------------------- #
# Retell-flavored native probes (pipeline-level gates — run NOW, no adapter)   #
#                                                                              #
# Shaped like what the Track A adapter emits per its PRD: telephony leg via    #
# the documented ``twilio`` default (Track A §5), TTS text+timing WITHOUT char #
# counts (Retell emits none -> no tts/playback spans -> D6/D7/D8 ABSENT), LLM  #
# turns whose decision_kind is adapter-inferred (flagged in the provider       #
# record, never agent-emitted).                                                #
# --------------------------------------------------------------------------- #

def _retell_like_probe(*, call_id="retell-gate-d1-probe", model="gpt-5",
                       decision_kind="route", output_tokens=10):
    """One-turn Retell-shaped probe: frontier route, short output.

    Mirrors ``test_vapi.py::_route_probe_call``'s firing shape (frontier
    ``gpt-5`` + ``route`` + <32 output tokens) so raw ``detect()`` fires D1.
    """
    return {
        "id": call_id,
        "scenario": "order_status",
        "started": "2026-09-04T09:00:00Z",
        "ended": "2026-09-04T09:01:00Z",
        "end_reason": "caller_hangup",
        "telephony": {"provider": "twilio", "direction": "inbound",
                      "billable_seconds": 30},
        "turns": [{"start_ms": 0, "end_ms": 5000,
                   "asr": {"transcript": "Where is my order?",
                           "start_ms": 200, "duration_ms": 1200},
                   "llm": {"model": model, "input_tokens": 900,
                           "output_tokens": output_tokens,
                           "decision_kind": decision_kind,
                           "decision": "order_status",
                           "output_text": "Checking.",
                           "start_ms": 1500, "duration_ms": 600},
                   # TTS text rides along (spoken window) but char counts are
                   # absent — Retell emits none, G2 forbids len(text).
                   "tts": {"text": "One moment, checking now.",
                           "start_ms": 2200, "duration_ms": 1500}}],
    }


def _retell_like_two_turn_probe():
    """Two LLM turns: turn 0 D1-eligible (route/gpt-5/short), turn 1 compose.

    Gives partial-inference gating something to split (mirrors the Vapi
    ``_route_probe_call`` two-LLM-turn shape).
    """
    obj = _retell_like_probe(call_id="retell-gate-partial")
    obj["turns"].append(
        {"start_ms": 5000, "end_ms": 10000,
         "asr": {"transcript": "Thanks, bye.", "start_ms": 5200, "duration_ms": 800},
         "llm": {"model": "gpt-5-mini", "input_tokens": 700, "output_tokens": 12,
                 "decision_kind": "compose", "decision": "respond",
                 "output_text": "You are welcome!",
                 "start_ms": 6200, "duration_ms": 600},
         "tts": {"text": "You are welcome!", "start_ms": 6900, "duration_ms": 1200}},
    )
    return obj


def _retell_like_acoustic_probe():
    """Compose turn with unvoiced output text: raw D6 fires (unvoiced compose).

    Mirrors ``test_pipeline.py::_absent_call`` — TTS text with NO acoustic
    fields + a mid-turn gap, so raw D6 AND D8 fire and the exclusion is
    load-bearing rather than vacuous.
    """
    return {
        "id": "retell-gate-acoustic",
        "scenario": "order_status",
        "started": "2026-09-04T09:00:00Z",
        "ended": "2026-09-04T09:01:00Z",
        "end_reason": "caller_hangup",
        "telephony": {"provider": "twilio", "direction": "inbound",
                      "billable_seconds": 60},
        "turns": [
            {
                "start_ms": 0, "end_ms": 8000,
                "asr": {"transcript": "Where is my order?",
                        "start_ms": 200, "duration_ms": 1200},
                "llm": {"model": "gpt-5-mini", "input_tokens": 700,
                        "output_tokens": 20, "decision_kind": "compose",
                        "decision": "report_status",
                        "output_text": "Your order ships tomorrow, arriving Thursday.",
                        "start_ms": 2000, "duration_ms": 600},
                "tts": {"text": "Your order ships tomorrow, arriving Thursday.",
                        "start_ms": 2700, "duration_ms": 2000},
            }
        ],
    }


def _retell_record(call_id, n_llm_turns, *, source="Retell export"):
    """Retell-flavored provider record: every LLM turn inferred, D1 excluded."""
    return {call_id: {
        "source": source,
        "note": ("source: retell export. decision_kind: inferred on "
                 f"{n_llm_turns} turn(s) (route-first / tool_select-on-mutation / "
                 "compose; never agent-emitted; D1 excluded from measured waste). "
                 "tts: text+timing only, no char counts -- D6/D7/D8 ABSENT."),
        "inferred_decision_turns": list(range(n_llm_turns)),
    }}


# --------------------------------------------------------------------------- #
# Gate 3 — acoustic absence -> D6/D7/D8 ABSENT (runs NOW)                       #
# --------------------------------------------------------------------------- #

def test_retell_probe_acoustic_absence_marks_d6_d7_d8_absent():
    """Gate 3a: a Retell-shaped call (no G2 char counts) reports D6/D7/D8
    ABSENT with 'no data for this input', zero findings there, and the classes
    in excluded_absent_classes. Defers sample-shape pins to Track A."""
    obj = _retell_like_acoustic_probe()
    report = run_call(obj, RATES, BASELINES,
                      provider=_retell_record(obj["id"], n_llm_turns=1))
    for class_id in ("6", "7", "8"):
        entry = report["coverage"][class_id]
        assert entry["status"] == "absent"
        assert "no data for this input" in entry["reason"]
    assert not any(f["class_id"] in (6, 7, 8) for f in report["findings"])
    # excluded_absent_classes names only classes raw detect() actually fired
    # (D7 with no acoustic pairs returns [], indistinguishable from zero, so
    # it is ABSENT-but-never-fired; D6/D8 fire and are dropped — see Gate 3b).
    assert 6 in report["excluded_absent_classes"]
    assert 8 in report["excluded_absent_classes"]
    assert report["source"] == "Retell export"


def test_retell_probe_absence_excludes_real_raw_d6_findings():
    """Gate 3b (load-bearing D6): raw detect() DOES fire D6 on the probe
    (unvoiced compose reads as dead tokens) but the pipelined report drops it.
    Follows test_pipeline.py::test_absence_excludes_real_raw_findings..."""
    obj = _retell_like_acoustic_probe()
    call = parse_call(obj)
    priced = price_trace(load(call, rates=RATES), RATES)
    raw_classes = {f.class_id for f in detect(priced, adjudicate(priced), BASELINES)}
    assert 6 in raw_classes  # the exclusion does real work, not vacuous
    report = run_call(call, RATES, BASELINES,
                      provider=_retell_record(call.id, n_llm_turns=1))
    assert 6 in report["excluded_absent_classes"]
    assert not any(f["class_id"] in (6, 7, 8) for f in report["findings"])


# --------------------------------------------------------------------------- #
# Gate 4 — inferred decision_kind -> never measured D1 (runs NOW)              #
# --------------------------------------------------------------------------- #

def test_retell_probe_inferred_decision_kind_never_measured_d1():
    """Gate 4a (load-bearing): raw detect() DOES fire D1 on the Retell-shaped
    probe (frontier route, short output), but the pipeline marks D1 ABSENT and
    drops the finding. Mirrors test_vapi.py::
    test_d1_never_reports_inferred_spans_as_measured."""
    obj = _retell_like_probe()
    call = parse_call(obj)
    assert len([t for t in call.turns if t.llm is not None]) == 1
    priced = price_trace(load(call, rates=RATES), RATES)
    raw_classes = {f.class_id for f in detect(priced, adjudicate(priced), BASELINES)}
    assert 1 in raw_classes  # the exclusion does real work, not vacuous
    report = run_call(call, RATES, BASELINES,
                      provider=_retell_record(call.id, n_llm_turns=1))
    assert report["coverage"]["1"]["status"] == "absent"
    assert "no data for this input" in report["coverage"]["1"]["reason"]
    assert not any(f["class_id"] == 1 for f in report["findings"])
    assert 1 in report["excluded_absent_classes"]


def test_retell_probe_partial_inference_filters_only_inferred_turns():
    """Gate 4b: a record naming an unrelated turn keeps D1 PRESENT + finding;
    naming turn 0 drops that turn's finding while the class stays PRESENT
    (turn 1 carries a measured-by-assumption kind). Mirrors test_vapi.py::
    test_partial_inference_filters_only_inferred_turns."""
    obj = _retell_like_two_turn_probe()
    call = parse_call(obj)
    # A record naming an unrelated turn: D1 stays PRESENT, finding kept.
    report = run_call(call, RATES, BASELINES,
                      provider={call.id: {"source": "Retell export", "note": "x",
                                          "inferred_decision_turns": [7]}})
    assert report["coverage"]["1"]["status"] == "present"
    assert any(f["class_id"] == 1 for f in report["findings"])
    # The same record naming turn 0: finding dropped, class still PRESENT.
    report = run_call(call, RATES, BASELINES,
                      provider={call.id: {"source": "Retell export", "note": "x",
                                          "inferred_decision_turns": [0]}})
    assert report["coverage"]["1"]["status"] == "present"
    assert not any(f["class_id"] == 1 for f in report["findings"])


def test_mixed_native_and_retell_fleet_margin_excluded_with_headline():
    """Gate 4c: a mixed fleet still prices D1 margin over the measured (native)
    leg; the Retell leg is excluded with margin_excluded==1 + headline note.
    Mirrors test_vapi.py::test_mixed_native_and_vapi_fleet_keeps_native_margin
    (this file owns the mixed-fleet margin stratum for Retell)."""
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
    retell_obj = _retell_like_probe(call_id="retell-gate-margin")
    retell_call = parse_call(retell_obj)
    native_call = parse_call(native)
    artifact, _ = run_calls([native_call, retell_call], RATES, BASELINES,
                            label="mixed", sample=False,
                            provider=_retell_record(retell_call.id, n_llm_turns=1))
    assert artifact["coverage_summary"]["margin_excluded"] == 1
    assert artifact["coverage_summary"]["calls_with_data_per_class"].get("1") == 1
    assert "1 provider-adapted call(s)" in artifact["fleet"]["_provenance"]["note"]
    # The native leg keeps its measured D1 finding (margin still priced).
    assert any(f["class_id"] == 1 and f["call_id"] == "native-001"
               for f in artifact["findings"])


# --------------------------------------------------------------------------- #
# Gate 1 — golden fixture -> expected IngestCall (needs Track A [+B])          #
# --------------------------------------------------------------------------- #

def _retell_probe_export(**overrides):
    """Inline Retell V2PhoneCallResponse-shaped probe (Track A §2 schema).

    Mirrors test_vapi.py::_route_probe_call style: greeting + complaint +
    lookup + fix-request + committed mutation + close over
    transcript_with_tool_calls (flat role-discriminated entries, the Get Call
    schema form), word-timed transcript_object alongside, call-level
    llm_token_usage. Billing-dispute narrative parallels the Vapi sample
    (distinct call_id).

    NOTE (Track A fix, 2026-09-15): the probe as first written used a nested
    single-key tool shape (``{"tool_call_invocation": {...}}``) the live
    Retell API never emits, and held only two caller utterances while Gate 1a
    asserts four turns (greeting + complaint + fix + close, mirroring the
    Vapi sample). Fixed to the flat entry shape plus the missing closing
    exchange; Track D owns any further probe changes.
    """
    base_ms = 1789203731000
    obj = {
        "call_id": "retell-gate-001",
        "agent_id": "agent-billing-synthetic",
        "agent_name": "Billing Assistant",
        "agent_version": 3,
        "call_status": "ended",
        "call_type": "phone_call",
        "direction": "inbound",
        "from_number": "+15550001111",
        "to_number": "+15550002222",
        "start_timestamp": base_ms,
        "end_timestamp": base_ms + 30000,
        "duration_ms": 30000,
        "disconnection_reason": "user_hangup",
        "transcript_object": [
            {"role": "agent", "content": "Hi, thanks for calling billing. How can I help?",
             "words": [{"word": "Hi,", "start": 0.0, "end": 0.3},
                       {"word": "thanks", "start": 0.3, "end": 0.6},
                       {"word": "for", "start": 0.6, "end": 0.8},
                       {"word": "calling", "start": 0.8, "end": 1.1},
                       {"word": "billing.", "start": 1.1, "end": 1.5}]},
            {"role": "user", "content": "Hi, I was charged twice this month.",
             "words": [{"word": "Hi,", "start": 2.0, "end": 2.2},
                       {"word": "I", "start": 2.2, "end": 2.3},
                       {"word": "was", "start": 2.3, "end": 2.5},
                       {"word": "charged", "start": 2.5, "end": 2.9},
                       {"word": "twice", "start": 2.9, "end": 3.2}]},
            {"role": "user", "content": "Yes, please fix it.",
             "words": [{"word": "Yes,", "start": 8.0, "end": 8.2},
                       {"word": "please", "start": 8.2, "end": 8.5},
                       {"word": "fix", "start": 8.5, "end": 8.7},
                       {"word": "it.", "start": 8.7, "end": 8.9}]},
            {"role": "agent", "content": "Done, I refunded the duplicate charge. Thanks, bye!",
             "words": [{"word": "Done,", "start": 20.0, "end": 20.3},
                       {"word": "I", "start": 20.3, "end": 20.4},
                       {"word": "refunded", "start": 20.4, "end": 20.8},
                       {"word": "the", "start": 20.8, "end": 21.0},
                       {"word": "duplicate", "start": 21.0, "end": 21.5}]},
            {"role": "user", "content": "No, that's all. Thanks, bye!",
             "words": [{"word": "No,", "start": 22.0, "end": 22.2},
                       {"word": "thanks,", "start": 22.2, "end": 22.5},
                       {"word": "bye!", "start": 22.5, "end": 22.8}]},
            {"role": "agent", "content": "You're welcome. Goodbye!",
             "words": [{"word": "You're", "start": 23.0, "end": 23.3},
                       {"word": "welcome.", "start": 23.3, "end": 23.7},
                       {"word": "Goodbye!", "start": 23.7, "end": 24.1}]},
        ],
        "transcript_with_tool_calls": [
            {"role": "agent", "content": "Hi, thanks for calling billing. How can I help?"},
            {"role": "user", "content": "Hi, I was charged twice this month."},
            {"role": "agent", "content": "Let me look that up."},
            {"role": "tool_call_invocation", "tool_call_id": "t1",
             "name": "lookup_invoices", "arguments": '{"customer": "C-1"}'},
            {"role": "tool_call_result", "tool_call_id": "t1",
             "content": '{"invoices": 2, "duplicate": true}',
             "successful": True},
            {"role": "user", "content": "Yes, please fix it."},
            {"role": "tool_call_invocation", "tool_call_id": "t2",
             "name": "adjust_billing",
             "arguments": '{"invoice": "INV-2", "action": "refund"}'},
            {"role": "tool_call_result", "tool_call_id": "t2",
             "content": '{"status": "refunded"}',
             "successful": True},
            {"role": "agent", "content": "Done, I refunded the duplicate charge. Thanks, bye!"},
            {"role": "user", "content": "No, that's all. Thanks, bye!"},
            {"role": "agent", "content": "You're welcome. Goodbye!"},
        ],
        "llm_token_usage": {"values": [1000, 1100, 900, 900], "average": 975.0,
                            "num_requests": 4},
        "call_cost": {"combined_cost": 87, "product_costs": []},
    }
    obj.update(overrides)
    return obj


def test_retell_inline_probe_maps_to_expected_ingest_call():
    """Gate 1a: inline Retell probe -> expected IngestCall (id, scenario slug,
    end_reason, agent_version string, telephony presence/direction, turn
    count + grouping, decision_kind sequence, token exact-sums,
    TTS-without-counts). SKIPS until Track A merges. Defers sample-shape pins
    to Track A test_retell.py::test_sample_maps_to_expected_ingest_call."""
    retell = _retell()
    obj = _retell_probe_export()
    # Caller-supplied ground truth for the backing model (Track A §3.5:
    # Retell names none). gpt-5 keeps the D1 tail below load-bearing: the
    # opening route turn (0 output tokens, <32) fires raw D1.
    call = _from_retell(retell, obj, llm_identity=("openai", "gpt-5"))
    assert call.id == "retell-gate-001"
    assert call.scenario == "billing_assistant"
    assert call.end_reason.value == "caller_hangup"
    assert call.agent_version == "retell/agent-billing-synthetic.v3"
    assert call.telephony is not None
    assert call.telephony.direction.value == "inbound"
    assert call.telephony.billable_seconds == 30
    assert len(call.turns) == 4

    opening, middle, mutation, close = call.turns
    assert opening.asr is None and opening.speaker_first.value == "agent"
    assert middle.asr is not None and middle.asr.transcript.startswith("Hi, I was charged twice")
    # §5 inference rules: route-first, tool_select-on-mutation, compose.
    assert opening.llm.decision_kind.value == "route"
    assert middle.llm.decision_kind.value == "compose"
    assert mutation.llm.decision_kind.value == "tool_select"
    assert mutation.llm.decision == "adjust_billing"
    assert close.llm.decision_kind.value == "compose"

    # Tools: lookup reads effect=none; committed mutation resolves committed.
    lookup = middle.tools[0]
    assert (lookup.name, lookup.kind.value, lookup.effect.value) == (
        "lookup_invoices", "lookup", "none")
    adjust = mutation.tools[0]
    assert (adjust.name, adjust.kind.value, adjust.effect.value,
            adjust.status.value) == ("adjust_billing", "mutation", "committed", "ok")

    # Tokens: exact-sum even split of the call totals across 4 LLM turns.
    # Track A treatment: values land as input_tokens, output_tokens stay 0
    # (output cost unmeasured, not zero) — pin both halves.
    total_prompt = sum(obj["llm_token_usage"]["values"])
    assert sum(t.llm.input_tokens for t in call.turns) == total_prompt
    assert all(t.llm.output_tokens == 0 for t in call.turns if t.llm)

    # TTS text rides along but char counts are absent (G2: no stand-in).
    assert all(t.tts is not None and t.tts.text for t in call.turns)
    assert all(t.tts.chars_synthesized is None and t.tts.chars_played is None
               for t in call.turns)

    # The adapted probe flows through the pipeline with D1/D6/D7/D8 ABSENT.
    # Load-bearing for D1: raw detect() DOES fire on the opening route turn
    # (frontier gpt-5, 0 output tokens) but the report drops it.
    info = retell.provider_info(obj, call, sample=True)
    assert info["source"] == "Retell export (synthetic schema-conformant example)"
    priced = price_trace(load(call, rates=RATES), RATES)
    raw_classes = {f.class_id for f in detect(priced, adjudicate(priced), BASELINES)}
    assert 1 in raw_classes  # the D1 exclusion does real work, not vacuous
    report = run_call(call, RATES, BASELINES, provider={call.id: info})
    for class_id in ("1", "6", "7", "8"):
        assert report["coverage"][class_id]["status"] == "absent"
    assert not any(f["class_id"] == 1 for f in report["findings"])
    assert 1 in report["excluded_absent_classes"]


def test_retell_committed_sample_maps_to_expected_ingest_call():
    """Gate 1b: Track B's committed sample -> expected IngestCall + ABSENT
    acoustic/D1 envelope end to end. SKIPS until A+B merge (adapter + file)."""
    retell = _retell()
    sample = _retell_sample()
    assert sample["sample"] is True
    # Track A fix, 2026-09-15: Retell names no model, so the export path
    # requires caller-supplied llm_identity (Track A §3.5) -- same pattern as
    # _from_retell above. Track D owns any further changes here.
    calls = retell.from_retell_export(sample, llm_identity=("openai", "gpt-5-mini"))
    assert len(calls) == 1
    call = calls[0]
    assert call.end_reason.value == "caller_hangup"  # Track B: user_hangup sample
    assert call.telephony is not None
    info = retell.provider_info(sample, call, sample=True)
    assert set(info) == {"source", "note", "inferred_decision_turns"}
    report = run_call(call, RATES, BASELINES, provider={call.id: info})
    for class_id in ("1", "6", "7", "8"):
        assert report["coverage"][class_id]["status"] == "absent"
        assert "no data for this input" in report["coverage"][class_id]["reason"]


# --------------------------------------------------------------------------- #
# Gate 2 — unmapped enum -> loud error (needs Track A)                         #
# --------------------------------------------------------------------------- #

def test_retell_unmapped_disconnection_reason_raises():
    """Gate 2a: unknown disconnection_reason -> IngestError naming the value
    AND the disconnection_reason path. SKIPS until Track A merges. Defers the
    table pins to Track A test_retell.py::test_end_reason_mapping."""
    retell = _retell()
    with pytest.raises(IngestError) as excinfo:
        _from_retell(retell, _retell_probe_export(
            disconnection_reason="some-brand-new-retell-code"))
    assert "some-brand-new-retell-code" in str(excinfo.value)
    assert "disconnection_reason" in str(excinfo.value)


def test_retell_ongoing_call_status_raises():
    """Gate 2b: call_status 'ongoing' (non-ended call) -> IngestError (only
    ended calls are ingestible). SKIPS until Track A merges."""
    retell = _retell()
    with pytest.raises(IngestError):
        _from_retell(retell, _retell_probe_export(call_status="ongoing"))


# --------------------------------------------------------------------------- #
# P1 #6 verdict: STAYS DEFERRED (verify-or-defer — detector already ships).    #
#                                                                              #
# D9 tier-2 (terminal handoff with effect == rejected -> full-conversation     #
# waste, confidence 0.95) IS ALREADY IMPLEMENTED in                            #
# packages/detectors/src/turnstile_detectors/d09_escalation_debt.py (covered   #
# by test_d09_escalation_debt.py incl. native call-21_handoff_rejected). P1 #6 #
# is therefore verify-only: it fires IFF the Day-2 dataset holds a forwarded  #
# call with a failed transfer.                                                  #
#                                                                              #
# EVIDENCE (scanned 2026-09-15; updated post-A/B-merge — Retell inputs now     #
# exist, verdict unchanged):                                                    #
# * Committed Retell sample (packages/ingest/sample/                            #
#   retell-export.sample.json, Track B): disconnection_reason == "user_hangup"  #
#   (single value observed). transcript_with_tool_calls scanned for transfer /  #
#   handoff / forward / escalat / successful:false / failed / reject /          #
#   cancelled / bridged: ZERO hits. transfer_destination absent,                #
#   call_analysis null. No forwarded leg, no failed transfer.                   #
# * Vapi sample (packages/ingest/sample/vapi-export.sample.json): exactly one  #
#   endedReason observed: "customer-ended-call" (-> caller_hangup). No         #
#   "assistant-forwarded-call", no transfer leg, no tool failure.               #
# * Native sample (packages/ingest/sample/calls.json): "end_reason"            #
#   occurrences observed: caller_hangup x41, escalated x9; tool "effect"        #
#   occurrences observed: none x55, committed x25, pending x1, rejected x0.     #
#   The escalated legs carry transfer_to_human handoff tools but ZERO          #
#   rejected effects — i.e. no failed-transfer encoding.                       #
# * The ONLY rejected-handoff encoding in the repo is the synthetic golden     #
#   fixture fixtures/golden/21_handoff_rejected.json (already proving tier-2   #
#   works end to end) — not Day-2 provider data.                               #
#                                                                              #
# CONCLUSION: no forwarded-call-with-failed-transfer in any Day-2 dataset      #
# input -> P1 #6 STAYS DEFERRED per track-d §3.3 (PRD-sanctioned outcome, not  #
# a gap). Re-verify after Track C lands: grep the surfaced dataset for         #
# disconnection_reason in (call_transfer, transfer_bridged) + a failed         #
# outcome (transfer tool successful:false / error content), or any tool        #
# effect == rejected on a handoff leg. d09_escalation_debt.py UNTOUCHED.       #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# CLI: --provider retell end to end (Track B wiring + llm-identity fix)        #
# --------------------------------------------------------------------------- #

def test_cli_provider_retell_sample_end_to_end(tmp_path):
    """Bundled Retell sample runs flag-free (embedded agent_model ground truth).

    Mirrors test_vapi.py::test_cli_provider_vapi_end_to_end: envelope shape,
    synthetic source string, margin exclusion, index/detail agreement, D1 ABSENT.
    """
    from turnstile_ingest.__main__ import main
    _retell()  # adapter must be merged
    _retell_sample()  # committed sample must be present
    out = tmp_path / "retell-out"
    assert main(["--provider", "retell", "--out", str(out)]) == 0
    artifact = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert artifact["n"] == 1 and artifact["sample"] is True
    assert "source: Retell export (synthetic schema-conformant example)" in artifact["provenance"]
    assert artifact["coverage_summary"]["margin_excluded"] == 1
    for key in ("label", "n", "note", "provenance", "fleet",
                "coverage_summary", "calls", "findings"):
        assert key in artifact
    row = artifact["calls"][0]
    detail = json.loads((out / row["detail"]).read_text(encoding="utf-8"))
    assert detail["conv_cost"] == row["cost_usd"]
    assert detail["_provenance"]["coverage"]["1"]["status"] == "absent"


def test_cli_provider_retell_without_identity_fails_loud(tmp_path):
    """An export with agent turns but no ground truth fails naming llm_identity.

    The bundled sample stripped of its embedded agent_model key is exactly
    that export: no --llm-identity flag, no embedded key -> loud SystemExit
    carrying the engine's field path (never a traceback exit, never a default).
    """
    from turnstile_ingest.__main__ import main
    _retell()
    sample = _retell_sample()
    obj = {k: v for k, v in sample.items() if k != "agent_model"}
    path = tmp_path / "no-identity.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["--provider", "retell", "--in", str(path),
              "--out", str(tmp_path / "out")])
    assert "llm_identity" in str(excinfo.value)


def test_cli_provider_retell_llm_identity_flag_supplies_ground_truth(tmp_path):
    """--llm-identity SYSTEM/MODEL prices an export lacking the embedded key."""
    from turnstile_ingest.__main__ import main
    _retell()
    sample = _retell_sample()
    obj = {k: v for k, v in sample.items() if k != "agent_model"}
    path = tmp_path / "flag-identity.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    out = tmp_path / "flag-out"
    assert main(["--provider", "retell", "--in", str(path),
                 "--llm-identity", "openai/gpt-5-mini",
                 "--out", str(out)]) == 0
    artifact = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert artifact["n"] == 1
    assert artifact["coverage_summary"]["margin_excluded"] == 1
