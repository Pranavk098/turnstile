"""Author the realistic ingest SAMPLE fleet (Wave-3 B).

This writes ``sample/calls.json`` -- a deterministic, seeded, ~50-call fleet in
the external ingest format, authored to read like real voice-AI traffic:
six scenarios in an uneven mix, a spread of outcomes (resolved / escalated /
abandoned / misrouted / pending), varied waste, and a DELIBERATE acoustic mix
(some calls carry the optional G2 fields so D6/D7/D8 are measured, the rest
omit them so those classes are honestly ABSENT).

It is a SAMPLE, not real customer traffic -- the dashboard labels it as such,
and this file is the honest, reproducible record of exactly how it was made.
Regenerate the fleet + its pipeline report with:

    uv run python packages/ingest/sample/build_fleet.py
    uv run python -m turnstile_ingest --sample --out packages/ingest/data
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from turnstile_ingest.model import IngestCall

HERE = Path(__file__).resolve().parent
OUT = HERE / "calls.json"
SEED = 20260907
N_CALLS = 50

# Registry-required terminal mutation per scenario (turnstile_verdict.registry);
# None = informational (resolution rides on a clean close, not a mutation).
REQUIRED = {
    "billing_dispute": "adjust_billing",
    "refund": "process_refund",
    "cancel_subscription": "cancel_subscription",
    "appointment_reschedule": "reschedule_appointment",
    "order_status": None,
    "tech_support": None,
}
LOOKUP_TOOL = {
    "billing_dispute": "lookup_invoices",
    "refund": "lookup_order",
    "cancel_subscription": "lookup_account",
    "appointment_reschedule": "lookup_appointment",
    "order_status": "lookup_order",
    "tech_support": "search_kb",
}
# Uneven scenario mix (weights) -- real fleets are lopsided.
SCENARIO_WEIGHTS = {
    "billing_dispute": 26, "order_status": 22, "cancel_subscription": 18,
    "tech_support": 14, "refund": 12, "appointment_reschedule": 8,
}

OPENINGS = {
    "billing_dispute": [
        "Hi, I was charged twice for my {month} bill, can you fix that?",
        "There's a {amount} dollar fee on my account I never agreed to.",
        "My bill jumped this month and I don't understand why.",
        "This is the second time I'm calling about a double charge.",
    ],
    "refund": [
        "I want a refund for order {order}, it arrived broken.",
        "Can I get my money back? The item was never delivered.",
        "I returned order {order} two weeks ago and still no refund.",
    ],
    "order_status": [
        "Where is my order {order}? It was supposed to arrive yesterday.",
        "Can you tell me when order {order} will ship?",
        "I just want a tracking update on my recent order.",
        "Has order {order} left the warehouse yet?",
    ],
    "cancel_subscription": [
        "I'd like to cancel my subscription please.",
        "Please cancel my plan, I'm not using it anymore.",
        "How do I stop being billed every month?",
    ],
    "appointment_reschedule": [
        "I need to move my appointment on {month} to next week.",
        "Can we reschedule the visit I have booked?",
    ],
    "tech_support": [
        "My device won't connect to wifi, can you help?",
        "The app keeps crashing when I open it.",
        "I can't log in, it says my password is wrong.",
        "My internet has been down since this morning.",
    ],
}
ROUTE_REPLY = {
    "billing_dispute": ["Let me pull up your bill and sort that out.",
                        "I'm sorry about that, let me dig into the charge right now."],
    "refund": ["Let me look up that order and start a refund.",
               "I'll find your order and get the refund moving."],
    "order_status": ["Let me check the status of that order for you.",
                     "One moment, I'll pull up the tracking."],
    "cancel_subscription": ["I can help with that. Let me pull up your account.",
                            "Sure, let me find your subscription."],
    "appointment_reschedule": ["Happy to help, let me find your appointment.",
                               "Let me pull up your booking."],
    "tech_support": ["Let me look into that with you.",
                     "I can help troubleshoot, one moment."],
}
MID_REPLY = {
    "billing_dispute": "I found the charge from {month}. Let me apply the correction.",
    "refund": "I see order {order}. Processing the refund now.",
    "order_status": "Your order {order} shipped and is out for delivery today.",
    "cancel_subscription": "I found your plan. Cancelling it now.",
    "appointment_reschedule": "I see your booking. Moving it to the new date.",
    "tech_support": "Try restarting the router; here are the steps.",
}
CLOSINGS = ["You're all set, anything else? Okay, take care!",
            "That's done. Is there anything else? Great, goodbye!",
            "All sorted. Have a great day, bye!"]

rng = random.Random(SEED)


def _detail():
    return {
        "amount": rng.choice([49, 79, 120, 200, 35, 88]),
        "month": rng.choice(["August", "July", "September", "June"]),
        "order": f"{rng.randint(10000, 99999)}",
        "cust": f"C-{rng.randint(10000, 99999)}",
    }


def _tts(text, start, dur, acoustic, barge):
    t = {"text": text, "start_ms": start, "duration_ms": dur}
    if acoustic:
        synth = int(len(text) * 1.05) + rng.randint(0, 8)
        # barge-in: caller cut in, so a chunk was synthesized-but-never-played.
        played = int(synth * rng.uniform(0.45, 0.72)) if barge else synth
        t["chars_synthesized"] = synth
        t["chars_played"] = played
    return t


def _build_call(idx, scenario, outcome, acoustic):
    d = _detail()
    req = REQUIRED[scenario]
    look = LOOKUP_TOOL[scenario]
    # waste knobs (varied so different detectors fire across the fleet)
    # Most calls already run the cheap model (a real fleet is mostly optimized);
    # only a few over-provisioned calls carry recoverable routing waste (D1).
    over_model = rng.random() < 0.08            # D1: gpt-5 on a trivial route
    bloat = rng.random() < 0.30                 # D2: oversized context
    redundant = rng.random() < 0.22             # D3: repeated lookup
    route_model = "gpt-5" if over_model else rng.choices(
        ["gpt-5-nano", "gpt-5-mini"], weights=[82, 18])[0]
    base_in = 820 + (rng.randint(900, 1600) if bloat else rng.randint(0, 260))

    turns, t = [], 0

    def caller_turn(text, kind, decision, reply, tools=None, barge=False, cand=None):
        nonlocal t
        asr_dur = rng.randint(1800, 3200)
        llm_start = asr_dur + rng.randint(400, 900)
        tts_start = llm_start + rng.randint(500, 900)
        tts_dur = rng.randint(2600, 4600)
        end = tts_start + tts_dur + rng.randint(200, 700)
        turn = {
            "start_ms": t, "end_ms": t + end, "speaker_first": "caller", "barge_in": barge,
            "asr": {"transcript": text, "start_ms": 200, "duration_ms": asr_dur},
            "llm": {"model": route_model if kind == "route" else rng.choices(["gpt-5-nano", "gpt-5-mini"], weights=[85, 15])[0],
                    "input_tokens": base_in + rng.randint(0, 200),
                    "output_tokens": rng.randint(12, 30),
                    "decision_kind": kind, "decision": decision,
                    "output_text": reply, "start_ms": llm_start, "duration_ms": rng.randint(600, 1000)},
            "tts": _tts(reply, tts_start, tts_dur, acoustic, barge),
        }
        if cand:
            turn["llm"]["decision_candidates"] = cand
        if tools:
            turn["tools"] = tools
        t += end
        return turn

    def agent_turn(decision_kind, decision, reply, tools, barge=False):
        nonlocal t
        llm_start = rng.randint(400, 900)
        tts_start = llm_start + rng.randint(500, 900)
        tts_dur = rng.randint(2800, 5000)
        end = tts_start + tts_dur + rng.randint(200, 800)
        turn = {
            "start_ms": t, "end_ms": t + end, "speaker_first": "agent", "barge_in": barge,
            "tools": tools,
            "llm": {"model": rng.choices(["gpt-5-nano", "gpt-5-mini"], weights=[85, 15])[0],
                    "input_tokens": base_in + rng.randint(120, 500),
                    "output_tokens": rng.randint(16, 34),
                    "decision_kind": decision_kind, "decision": decision,
                    "output_text": reply, "start_ms": llm_start, "duration_ms": rng.randint(700, 1100)},
            "tts": _tts(reply, tts_start, tts_dur, acoustic, barge),
        }
        t += end
        return turn

    def tool(name, kind, effect, extra=None):
        a = {"customer_id": d["cust"]}
        if extra:
            a.update(extra)
        return {"name": name, "kind": kind, "effect": effect, "args": a,
                "start_ms": rng.randint(100, 700), "duration_ms": rng.randint(300, 900)}

    # turn 1: caller opening + route
    turns.append(caller_turn(OPENINGS[scenario][idx % len(OPENINGS[scenario])].format(**d),
                             "route", scenario, rng.choice(ROUTE_REPLY[scenario]),
                             cand=[scenario, "other"], barge=acoustic and rng.random() < 0.35))
    # turn 2: lookup (+ optional redundant lookup for D3)
    look_tools = [tool(look, "lookup", "none", {"ref": d["order"]})]
    if redundant:
        look_tools.append(tool(look, "lookup", "none", {"ref": d["order"], "retry": True}))
    turns.append(agent_turn("tool_select", look, MID_REPLY[scenario].format(**d), look_tools))

    if outcome == "resolved" and req:
        turns.append(agent_turn("compose", "complete_mutation", "Done, that's corrected now.",
                                [tool(req, "mutation", "committed", {"ref": d["order"]})]))
        turns.append(agent_turn("compose", "close_call", rng.choice(CLOSINGS), []))
        end_reason = "caller_hangup"
    elif outcome == "resolved" and not req:  # informational: clean close
        turns.append(agent_turn("compose", "close_call", rng.choice(CLOSINGS), []))
        end_reason = "caller_hangup"
    elif outcome == "escalated":
        # escalation debt: a few stalled turns before the handoff (D9)
        for _ in range(rng.randint(1, 2)):
            turns.append(agent_turn("escalate_check", "continue",
                                    "Let me check one more thing before I hand you over.", []))
        turns.append(agent_turn("escalate_check", "escalate", "I'm connecting you to a specialist now.",
                                [tool("transfer_to_human", "handoff", "committed", {"queue": scenario})]))
        end_reason = "escalated"
    elif outcome == "abandoned":  # informational scenario, caller hangs up mid slot-fill, no close
        turns.append(agent_turn("slot_fill", "request_slot",
                                "Can you confirm the last four digits on the account?", []))
        end_reason = "caller_hangup"
    elif outcome == "misrouted" and req:  # committed the WRONG mutation
        wrong = rng.choice([v for k, v in REQUIRED.items() if v and v != req])
        turns.append(agent_turn("compose", "complete_mutation", "Okay, I've applied that.",
                                [tool(wrong, "mutation", "committed", {"ref": d["order"]})]))
        end_reason = "caller_hangup"
    elif outcome == "pending" and req:  # mutation didn't commit
        turns.append(agent_turn("compose", "complete_mutation",
                                "I've submitted the change; it may take a moment.",
                                [tool(req, "mutation", "pending", {"ref": d["order"]})]))
        end_reason = "caller_hangup"
    else:  # fallback: informational clean close
        turns.append(agent_turn("compose", "close_call", rng.choice(CLOSINGS), []))
        end_reason = "caller_hangup"

    total_s = max(1, t // 1000)
    hh = 8 + (idx % 10)
    return {
        "id": f"ing-2026091{idx // 10}-{idx % 100:03d}",
        "scenario": scenario,
        "agent_version": rng.choice(["voice-agent@3.2.1", "voice-agent@3.3.0", "voice-agent@3.1.7"]),
        "started": f"2026-09-1{idx // 10}T{hh:02d}:{(idx * 7) % 60:02d}:05Z",
        "ended": f"2026-09-1{idx // 10}T{hh:02d}:{(idx * 7) % 60:02d}:{min(59, 5 + total_s):02d}Z",
        "end_reason": end_reason,
        "telephony": {"provider": "twilio",
                      "direction": "inbound", "billable_seconds": total_s + rng.randint(1, 4)},
        "turns": turns,
    }


def build():
    scenarios = list(SCENARIO_WEIGHTS)
    weights = [SCENARIO_WEIGHTS[s] for s in scenarios]
    # outcome mix by whether the scenario requires a mutation
    mut_outcomes = ["resolved"] * 6 + ["escalated"] * 2 + ["misrouted"] + ["pending"]
    info_outcomes = ["resolved"] * 6 + ["escalated"] * 2 + ["abandoned"] * 2
    calls = []
    for i in range(N_CALLS):
        scenario = rng.choices(scenarios, weights=weights, k=1)[0]
        req = REQUIRED[scenario]
        outcome = rng.choice(mut_outcomes if req else info_outcomes)
        acoustic = rng.random() < 0.45  # ~45% carry G2 acoustic fields
        obj = _build_call(i, scenario, outcome, acoustic)
        IngestCall.model_validate(obj)  # fail loud on any invalid authored call
        calls.append(obj)
    payload = {
        "sample": True,
        "note": ("Authored realistic SAMPLE fleet -- NOT real customer traffic. "
                 f"Deterministic (seed {SEED}); regenerate with build_fleet.py."),
        "calls": calls,
    }
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    # quick distribution report
    from collections import Counter
    sc = Counter(c["scenario"] for c in calls)
    er = Counter(c["end_reason"] for c in calls)
    ac = sum(1 for c in calls if any(
        (t.get("tts") or {}).get("chars_synthesized") is not None for t in c["turns"]))
    print(f"wrote {OUT}  n={len(calls)}")
    print("scenarios:", dict(sc))
    print("end_reasons:", dict(er))
    print(f"acoustic-present calls: {ac}/{len(calls)}")


if __name__ == "__main__":
    build()
