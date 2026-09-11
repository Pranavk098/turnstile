"""Open-loop harness + resolution-rule tests (TDD -- written FIRST, red).

All free: a canned mock policy drives the loop (the paid run only swaps in
the capped LLM + the real judge). Rules under test:

- divergence: live decision path != baseline (mock P1 policy) path;
- rule 1 (registry-grounded): mutation intent -> True iff the required tool
  committed AND the executed verdict is RESOLVED; lookup/unregistered -> None;
- rule 2 (LLM judge): fake chat client RESOLVED/UNRESOLVED/garbage parsing.
"""
from __future__ import annotations

from pathlib import Path

from turnstile_ingest import parse_call
from turnstile_schema import load_rates

from turnstile_live.openloop import (
    BUDGET_CAP_USD,
    EXTRA_SCRIPTS,
    SCRIPT_SET,
    candidates_for,
    enforce_budget,
    estimate_worst_case_usd,
    rule1_registry,
    rule2_judge,
    run_baseline,
    run_live,
    summarize,
)
from turnstile_live.policy import decide as mock_decide
from turnstile_live.voice import LlmDecision, kind_for_label

RATES = load_rates(Path(__file__).parents[3] / "pricing" / "rates.yaml")


class MockLivePolicy:
    """Canned decisions per (scenario, turn_index); falls back to the mock
    baseline policy anywhere unscripted."""

    def __init__(self, script: dict) -> None:
        self._script = script

    def decide(self, scenario, transcript, turn_index, candidates=None):
        key = (scenario, turn_index)
        if key in self._script:
            kind, label, reply = self._script[key]
            return LlmDecision(kind, label, reply, 700, 20, False, 0.0)
        mock = mock_decide(scenario, transcript, turn_index)
        return LlmDecision(mock.decision_kind, mock.decision, mock.reply, 700, 20, True, 0.0)


def _conv(scenario: str, turn_index: int = 0):
    return next(c for c in SCRIPT_SET if c.scenario == scenario)


# --------------------------------------------------------------------------- #
# Script set shape                                                             #
# --------------------------------------------------------------------------- #

def test_script_set_has_24_conversations_across_6_scenarios():
    assert len(SCRIPT_SET) == 24
    by_scenario: dict[str, int] = {}
    ids = set()
    for conv in SCRIPT_SET:
        by_scenario[conv.scenario] = by_scenario.get(conv.scenario, 0) + 1
        assert len(conv.caller_texts) == 3
        assert conv.id not in ids
        ids.add(conv.id)
    assert sorted(by_scenario) == [
        "appointment_reschedule", "billing_dispute", "cancel_subscription",
        "order_status", "refund", "tech_support",
    ]
    assert set(by_scenario.values()) == {4}


def test_extra_scripts_extend_each_scenario_without_touching_the_set():
    assert len(EXTRA_SCRIPTS) == 12
    assert len(SCRIPT_SET) == 24  # P3's frozen gate
    by_scenario: dict[str, int] = {}
    base_ids = {c.id for c in SCRIPT_SET}
    for conv in EXTRA_SCRIPTS:
        by_scenario[conv.scenario] = by_scenario.get(conv.scenario, 0) + 1
        assert len(conv.caller_texts) == 3
        assert conv.id not in base_ids
    assert set(by_scenario.values()) == {2}


# --------------------------------------------------------------------------- #
# Divergence                                                                   #
# --------------------------------------------------------------------------- #

def test_identical_policies_do_not_diverge():
    conv = _conv("refund")
    base = run_baseline(conv)
    live, _call = run_live(conv, MockLivePolicy({}), RATES)
    assert live.divergent_from(base) is False


def test_forked_policy_diverges_on_the_scripted_turn():
    conv = _conv("refund")
    base = run_baseline(conv)
    fork = MockLivePolicy({("refund", 1): ("tool_select", "lookup_account", "Checking the account.")})
    live, _call = run_live(conv, fork, RATES)
    assert live.divergent_from(base) is True


# --------------------------------------------------------------------------- #
# Rule 1: registry-grounded                                                    #
# --------------------------------------------------------------------------- #

def test_rule1_true_when_required_tool_committed_and_resolved():
    assert rule1_registry("refund", [("process_refund", "committed")], "RESOLVED") is True


def test_rule1_false_when_required_tool_missing():
    assert rule1_registry("refund", [("lookup_account", "none")], "RESOLVED") is False


def test_rule1_false_when_committed_but_unresolved():
    assert rule1_registry("refund", [("process_refund", "committed")], "ABANDONED") is False


def test_rule1_none_for_lookup_intent():
    assert rule1_registry("order_status", [], "RESOLVED") is None


def test_rule1_none_for_unregistered_scenario():
    assert rule1_registry("not_a_real_scenario", [], "RESOLVED") is None


# --------------------------------------------------------------------------- #
# Rule 2: LLM judge (fake chat client)                                         #
# --------------------------------------------------------------------------- #

def _fake_chat(reply: str):
    def call(messages: list[dict]) -> tuple[str, int, int]:
        return reply, 100, 5

    return call


def test_rule2_resolved_is_true():
    assert rule2_judge(_fake_chat("RESOLVED"), "refund", "transcript") == (True, 100, 5)


def test_rule2_unresolved_is_false():
    assert rule2_judge(_fake_chat("unresolved"), "refund", "transcript") == (False, 100, 5)


def test_rule2_garbage_is_none():
    assert rule2_judge(_fake_chat("maybe, unclear"), "refund", "transcript")[0] is None


# --------------------------------------------------------------------------- #
# Budget guard                                                                 #
# --------------------------------------------------------------------------- #

def test_estimate_for_planned_run_is_under_cap():
    assert estimate_worst_case_usd(n_convos=24, turns_each=3) < BUDGET_CAP_USD
    enforce_budget(n_convos=24, turns_each=3)  # must not raise


def test_oversized_run_refuses():
    try:
        enforce_budget(n_convos=10000, turns_each=10)
    except RuntimeError as exc:
        assert "$2" in str(exc) or "2.00" in str(exc)
    else:
        raise AssertionError("expected budget refusal")


# --------------------------------------------------------------------------- #
# Per-turn candidates (fairness: the offered set must cover the baseline's    #
# reachable labels, plus the registry-required tool -- offering less forces   #
# divergence and scores preservation 0.0 by construction).                     #
# --------------------------------------------------------------------------- #

def test_turn_zero_candidates_are_the_route_universe():
    cands = candidates_for("refund", 0)
    assert "refund" in cands and "other" in cands
    assert "close_call" not in cands


def test_later_turns_offer_actions_plus_the_required_tool():
    cands = candidates_for("refund", 1)
    assert "lookup_invoices" in cands
    assert "close_call" in cands and "escalate" in cands
    assert "process_refund" in cands  # registry-required terminal tool
    assert "order_status" not in cands  # baseline can't emit these here


def test_lookup_scenarios_offer_no_required_tool():
    cands = candidates_for("order_status", 2)
    assert "lookup_invoices" in cands and "close_call" in cands


def test_kind_mapping():
    assert kind_for_label("lookup_invoices", 1) == "tool_select"
    assert kind_for_label("escalate", 1) == "escalate_check"
    assert kind_for_label("close_call", 2) == "compose"
    assert kind_for_label("refund", 0) == "route"


def test_escalate_runs_the_handoff_tool():
    conv = _conv("refund")
    policy = MockLivePolicy({("refund", 1): ("escalate_check", "escalate", "Connecting you.")})
    live, _call = run_live(conv, policy, RATES)
    tools = [(n, e) for t in live.turns for n, e in t.tools]
    assert ("transfer_to_agent", "committed") in tools


# --------------------------------------------------------------------------- #
# Emission + summary                                                           #
# --------------------------------------------------------------------------- #

def test_live_run_emits_a_valid_ingest_call():
    conv = _conv("refund")
    _live, call = run_live(conv, MockLivePolicy({}), RATES)
    parsed = parse_call(call.model_dump(mode="json"))
    assert parsed.id == conv.id
    assert len(parsed.turns) == 3


def test_summarize_keeps_both_rules_separate():
    rows = [
        {"divergent": True, "rule1": True, "rule2": True},
        {"divergent": True, "rule1": False, "rule2": None},
        {"divergent": True, "rule1": None, "rule2": True},
        {"divergent": False, "rule1": None, "rule2": None},
    ]
    figures = summarize(rows)
    assert figures["n_divergent"] == 3
    assert figures["n_undecidable"] == 1
    assert figures["registry"] == 0.5  # 1/2 over decidable only
    assert figures["llm_judge"] == 1.0  # 2/2 (parse-fail excluded)
    assert figures["n_judge_unparsed"] == 1
    assert "identity" not in figures and "modeled" not in figures
