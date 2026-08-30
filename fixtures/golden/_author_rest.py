# fixtures/golden/_author_rest.py  (run once to emit fixtures 01-06, 08-19)
from pathlib import Path
from _builder import conv, llm, tts, playback, tool, leg, context, asr, dump
from turnstile_schema import Trace, Turn, ToolCall

HERE = Path(__file__).parent


def cid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


# ---- 01_over_model: frontier gpt-5 used for a route decision, output_tokens<32 ----
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=3000,
          llm=[llm("l0", "openai/gpt-5", "route", "order_status",
                   ["order_status", "billing"], "Order status.", 500, 15)],
          tts=[tts("t0", "Order status.", 13, 1.0)],
          playback=[playback("p0", 13, 1.0)])
dump(Trace(conversation=conv(cid(1), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(3)), HERE / "01_over_model.json")

# ---- 02_context_bloat: input_tokens rises >400/turn across 5 turns, cache_read always 0 ----
in_toks = [800, 1300, 1900, 2600, 3400]
turns02 = []
for i, tok in enumerate(in_toks):
    start = i * 3000
    turns02.append(Turn(
        turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
        wall_start_ms=start, wall_end_ms=start + 3000,
        llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", "continue",
                 ["continue"], f"Response {i}.", tok, 20, cache_read=0)],
        tts=[tts(f"t{i}", f"Response {i}.", 12, 1.0)],
        playback=[playback(f"p{i}", 12, 1.0)]))
dump(Trace(conversation=conv(cid(2), "billing_dispute", "caller_hangup"),
           turns=turns02, telephony=leg(15)), HERE / "02_context_bloat.json")

# ---- 03_redundant_retrieval: tool.call(retrieval) re-fetches a doc already in an
#      earlier turn's context.assemble.retrieved_doc_ids ----
DOC_ID = "doc_refund_policy_7"
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=3000,
          context=context("c0", context_tokens=900, history_tokens=200,
                           system_tokens=100, retrieved_tokens=600,
                           retrieved_doc_ids=[DOC_ID]),
          llm=[llm("l0", "openai/gpt-5-mini", "route", "refund",
                   ["refund", "order_status"], "Let me look into that.", 700, 18)],
          tts=[tts("t0", "Let me look into that.", 22, 1.5)],
          playback=[playback("p0", 22, 1.5)])
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=3000, wall_end_ms=6000,
          llm=[llm("l1", "openai/gpt-5-mini", "slot_fill", "order_number",
                   ["order_number"], "What is your order number?", 750, 14)],
          tts=[tts("t1", "What is your order number?", 27, 1.8)],
          playback=[playback("p1", 27, 1.8)])
redundant_tool = ToolCall.model_validate({
    "span_id": "tool2", "turnstile.tool_name": "search_kb",
    "turnstile.args_hash": "sha256:kbq1",
    "turnstile.args_json": f'{{"query": "refund policy", "doc_id": "{DOC_ID}"}}',
    "turnstile.result_hash": "sha256:kbr1", "turnstile.latency_ms": 400,
    "turnstile.tool_kind": "retrieval"})
t2 = Turn(turn_index=2, speaker_first="agent", wall_start_ms=6000, wall_end_ms=9000,
          tools=[redundant_tool],
          llm=[llm("l2", "openai/gpt-5-mini", "compose", "explain_refund",
                   ["explain_refund"], "Here is our refund policy again.", 800, 25)],
          tts=[tts("t2", "Here is our refund policy again.", 33, 2.1)],
          playback=[playback("p2", 33, 2.1)])
dump(Trace(conversation=conv(cid(3), "refund", "caller_hangup"),
           turns=[t0, t1, t2], telephony=leg(9)), HERE / "03_redundant_retrieval.json")

# ---- 04_turn_inflation: 14 turns for order_status (baseline p50=8), RESOLVED-ending ----
def inflate_turns(n, scenario_offset=0):
    ts = []
    for i in range(n):
        start = i * 2000
        ts.append(Turn(
            turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
            wall_start_ms=start, wall_end_ms=start + 2000,
            llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", f"step_{i}",
                     [f"step_{i}"], f"Okay, checking step {i}.", 500 + i * 5, 15)],
            tts=[tts(f"t{i}", f"Okay, checking step {i}.", 20, 1.3)],
            playback=[playback(f"p{i}", 20, 1.3)]))
    return ts

turns04 = inflate_turns(14)
dump(Trace(conversation=conv(cid(4), "order_status", "caller_hangup"),
           turns=turns04, telephony=leg(28)), HERE / "04_turn_inflation.json")

# ---- 05_reprompt_loop: same slot_fill decision_chosen twice, consecutive turns, no fill between ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=3000,
          llm=[llm("l0", "openai/gpt-5-mini", "slot_fill", "phone_number",
                   ["phone_number"], "What's your phone number?", 600, 16)],
          tts=[tts("t0", "What's your phone number?", 27, 1.7)],
          playback=[playback("p0", 27, 1.7)])
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=3000, wall_end_ms=6000,
          asr=[asr("a1", "uhh sorry what", audio_seconds=1.2)],
          llm=[llm("l1", "openai/gpt-5-mini", "slot_fill", "phone_number",
                   ["phone_number"], "Sorry, could you repeat your phone number?",
                   650, 17)],
          tts=[tts("t1", "Sorry, could you repeat your phone number?", 44, 2.5)],
          playback=[playback("p1", 44, 2.5)])
dump(Trace(conversation=conv(cid(5), "account_update", "caller_hangup"),
           turns=[t0, t1], telephony=leg(6)), HERE / "05_reprompt_loop.json")

# ---- 06_dead_tokens: llm output_text with no matching tts.synthesize in the turn ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=2000,
          llm=[llm("l0", "openai/gpt-5-mini", "compose", "internal_note",
                   ["internal_note"], "Here is extra info nobody hears.", 500, 22)])
dump(Trace(conversation=conv(cid(6), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(2)), HERE / "06_dead_tokens.json")

# ---- 08_silence_tax: turn wall span far exceeds sum of child-span latencies (>200ms gap),
#      meter (telephony) still running, no playback covering the gap ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=6000,
          tools=[tool("tool0", "lookup_order", "sha256:lk1", "lookup", latency=300)],
          llm=[llm("l0", "openai/gpt-5-mini", "compose", "report_status",
                   ["report_status"], "Checking now.", 600, 14, latency=500)])
# wall span = 6000ms; span latencies sum = 300 + 500 = 800ms; gap = 5200ms >> 200ms
dump(Trace(conversation=conv(cid(8), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(6)), HERE / "08_silence_tax.json")

# ---- 09_escalation_debt: escalation implied at turn 3, handoff 9 turns later (turn 12) ----
def escalation_turns(no_return_idx, total_turns, escalate_kind="escalate_check"):
    ts = []
    for i in range(total_turns):
        start = i * 2000
        if i == no_return_idx:
            ts.append(Turn(
                turn_index=i, speaker_first="caller", wall_start_ms=start,
                wall_end_ms=start + 2000,
                llm=[llm(f"l{i}", "openai/gpt-5-mini", escalate_kind, "escalate",
                         ["resolve", "escalate"], "This needs a human.", 700, 20)],
                tts=[tts(f"t{i}", "This needs a human.", 19, 1.3)],
                playback=[playback(f"p{i}", 19, 1.3)]))
        elif i == total_turns - 1:
            ts.append(Turn(
                turn_index=i, speaker_first="agent", wall_start_ms=start,
                wall_end_ms=start + 2000,
                tools=[tool(f"tool{i}", "transfer_to_agent", f"sha256:xfer{i}",
                            "handoff")],
                llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", "transfer",
                         ["transfer"], "Transferring you now.", 650, 18)],
                tts=[tts(f"t{i}", "Transferring you now.", 22, 1.5)],
                playback=[playback(f"p{i}", 22, 1.5)]))
        else:
            ts.append(Turn(
                turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                wall_start_ms=start, wall_end_ms=start + 2000,
                llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", f"stall_{i}",
                         [f"stall_{i}"], "Let me keep looking into this.", 600, 16)],
                tts=[tts(f"t{i}", "Let me keep looking into this.", 28, 1.8)],
                playback=[playback(f"p{i}", 28, 1.8)]))
    return ts

turns09 = escalation_turns(no_return_idx=3, total_turns=13)
dump(Trace(conversation=conv(cid(9), "billing_dispute", "escalated"),
           turns=turns09, telephony=leg(26)), HERE / "09_escalation_debt.json")

# ---- 10_tool_thrash: two tool.call spans, same tool_name, identical args_hash ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=3000,
          tools=[tool("tool0", "update_address", "sha256:dupAddr1", "mutation",
                      result_hash="sha256:updok1")],
          llm=[llm("l0", "openai/gpt-5-mini", "compose", "confirm_update",
                   ["confirm_update"], "Updating your address.", 500, 14)])
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=3000, wall_end_ms=6000,
          tools=[tool("tool1", "update_address", "sha256:dupAddr1", "mutation",
                      result_hash="sha256:updok1")],
          llm=[llm("l1", "openai/gpt-5-mini", "compose", "confirm_update_retry",
                   ["confirm_update_retry"], "Trying that update again.", 520, 15)])
dump(Trace(conversation=conv(cid(10), "account_update", "caller_hangup"),
           turns=[t0, t1], telephony=leg(6)), HERE / "10_tool_thrash.json")

# ---- 11_multi_waste_a: over_model(01) + context_bloat(02) + silence_tax(08) ----
in_toks_11 = [800, 1300, 1900, 2600, 3400]
turns11 = []
for i, tok in enumerate(in_toks_11):
    start = i * 4000
    end = start + (5000 if i == 0 else 3000)  # turn 0 has an inflated wall span -> gap
    kind = "route" if i == 0 else "compose"
    model = "openai/gpt-5" if i == 0 else "openai/gpt-5-mini"
    out_tok = 15 if i == 0 else 20  # <32 on the frontier turn, satisfying 01
    llm_span = llm(f"l{i}", model, kind, "handle_billing", ["handle_billing"],
                   f"Response {i}.", tok, out_tok, latency=500, cache_read=0)
    if i == 0:
        # turn 0: zero tts/playback spans despite a 5000ms billed wall span --
        # identical in kind to 08_silence_tax's clean D8 encoding (total audio
        # silence for a billed turn), not a wall-minus-latency arithmetic gap.
        turns11.append(Turn(
            turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
            wall_start_ms=start, wall_end_ms=end, llm=[llm_span]))
    else:
        turns11.append(Turn(
            turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
            wall_start_ms=start, wall_end_ms=end, llm=[llm_span],
            tts=[tts(f"t{i}", f"Response {i}.", 12, 1.0)],
            playback=[playback(f"p{i}", 12, 1.0)]))
dump(Trace(conversation=conv(cid(11), "billing_dispute", "caller_hangup"),
           turns=turns11, telephony=leg(20)), HERE / "11_multi_waste_a.json")

# ---- 12_multi_waste_b: dead_tokens(06) + barge_in(07) + tool_thrash(10) ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=2000,
          llm=[llm("l0", "openai/gpt-5-mini", "compose", "internal_note",
                   ["internal_note"], "Here is extra info nobody hears.", 500, 22)])
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=2000, wall_end_ms=8000,
          barge_in=True,
          llm=[llm("l1", "openai/gpt-5", "compose", "long_explanation",
                   ["long_explanation"],
                   "Here is a very long explanation of our refund policy ...",
                   1200, 140)],
          tts=[tts("t1", "Here is a very long explanation of our refund policy "
                         "that continues well past where the caller interrupts.",
                   184, 11.2)],
          playback=[playback("p1", 61, 3.8, truncated_by="barge_in")])
t2 = Turn(turn_index=2, speaker_first="agent", wall_start_ms=8000, wall_end_ms=11000,
          tools=[tool("tool2", "update_address", "sha256:dupAddr9", "mutation",
                      result_hash="sha256:updok9")],
          llm=[llm("l2", "openai/gpt-5-mini", "compose", "confirm_update",
                   ["confirm_update"], "Updating your address.", 500, 14)])
t3 = Turn(turn_index=3, speaker_first="agent", wall_start_ms=11000, wall_end_ms=14000,
          tools=[tool("tool3", "update_address", "sha256:dupAddr9", "mutation",
                      result_hash="sha256:updok9")],
          llm=[llm("l3", "openai/gpt-5-mini", "compose", "confirm_update_retry",
                   ["confirm_update_retry"], "Trying that update again.", 520, 15)])
dump(Trace(conversation=conv(cid(12), "refund", "caller_hangup"),
           turns=[t0, t1, t2, t3], telephony=leg(14)), HERE / "12_multi_waste_b.json")

# ---- 13_multi_waste_c: redundant_retrieval(03) + turn_inflation(04) + reprompt_loop(05) ----
DOC_ID_13 = "doc_order_faq_3"
turns13 = []
turns13.append(Turn(
    turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=2000,
    context=context("c0", context_tokens=900, history_tokens=200, system_tokens=100,
                     retrieved_tokens=600, retrieved_doc_ids=[DOC_ID_13]),
    llm=[llm("l0", "openai/gpt-5-mini", "route", "order_status",
             ["order_status"], "Let me check that.", 700, 18)],
    tts=[tts("t0", "Let me check that.", 18, 1.4)],
    playback=[playback("p0", 18, 1.4)]))
turns13.append(Turn(
    turn_index=1, speaker_first="agent", wall_start_ms=2000, wall_end_ms=4000,
    llm=[llm("l1", "openai/gpt-5-mini", "slot_fill", "order_number",
             ["order_number"], "What is your order number?", 750, 14)],
    tts=[tts("t1", "What is your order number?", 27, 1.8)],
    playback=[playback("p1", 27, 1.8)]))
turns13.append(Turn(
    turn_index=2, speaker_first="agent", wall_start_ms=4000, wall_end_ms=6000,
    llm=[llm("l2", "openai/gpt-5-mini", "slot_fill", "order_number",
             ["order_number"], "Sorry, could you repeat your order number?",
             770, 16)],
    tts=[tts("t2", "Sorry, could you repeat your order number?", 43, 2.4)],
    playback=[playback("p2", 43, 2.4)]))
redundant_tool_13 = ToolCall.model_validate({
    "span_id": "tool3", "turnstile.tool_name": "search_kb",
    "turnstile.args_hash": "sha256:kbq2",
    "turnstile.args_json": f'{{"query": "order faq", "doc_id": "{DOC_ID_13}"}}',
    "turnstile.result_hash": "sha256:kbr2", "turnstile.latency_ms": 400,
    "turnstile.tool_kind": "retrieval"})
turns13.append(Turn(
    turn_index=3, speaker_first="agent", wall_start_ms=6000, wall_end_ms=8000,
    tools=[redundant_tool_13],
    llm=[llm("l3", "openai/gpt-5-mini", "compose", "explain_order",
             ["explain_order"], "Here is our order FAQ again.", 800, 24)],
    tts=[tts("t3", "Here is our order FAQ again.", 30, 2.0)],
    playback=[playback("p3", 30, 2.0)]))
# pad out to 14 turns total for turn_inflation (04)
for i in range(4, 14):
    start = i * 2000
    turns13.append(Turn(
        turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
        wall_start_ms=start, wall_end_ms=start + 2000,
        llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", f"step_{i}",
                 [f"step_{i}"], f"Okay, checking step {i}.", 500 + i * 5, 15)],
        tts=[tts(f"t{i}", f"Okay, checking step {i}.", 20, 1.3)],
        playback=[playback(f"p{i}", 20, 1.3)]))
dump(Trace(conversation=conv(cid(13), "order_status", "caller_hangup"),
           turns=turns13, telephony=leg(28)), HERE / "13_multi_waste_c.json")

# ---- 14_escalation_early: escalation implied at turn 3 == final turn == handoff (debt=0) ----
turns14 = []
for i in range(3):
    start = i * 2000
    turns14.append(Turn(
        turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
        wall_start_ms=start, wall_end_ms=start + 2000,
        llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", f"try_{i}",
                 [f"try_{i}"], "Let me try to help with that.", 550, 16)],
        tts=[tts(f"t{i}", "Let me try to help with that.", 27, 1.8)],
        playback=[playback(f"p{i}", 27, 1.8)]))
turns14.append(Turn(
    turn_index=3, speaker_first="caller", wall_start_ms=6000, wall_end_ms=8000,
    tools=[tool("tool3", "transfer_to_agent", "sha256:xfer3", "handoff")],
    llm=[llm("l3", "openai/gpt-5-mini", "escalate_check", "escalate",
             ["resolve", "escalate"], "Transferring you to a specialist now.",
             700, 20)],
    tts=[tts("t3", "Transferring you to a specialist now.", 39, 2.4)],
    playback=[playback("p3", 39, 2.4)]))
dump(Trace(conversation=conv(cid(14), "billing_dispute", "escalated"),
           turns=turns14, telephony=leg(8)), HERE / "14_escalation_early.json")

# ---- 15_escalation_late: escalation implied at penultimate turn, handoff at final (debt=1) ----
turns15 = escalation_turns(no_return_idx=6, total_turns=8, escalate_kind="escalate_check")
dump(Trace(conversation=conv(cid(15), "billing_dispute", "escalated"),
           turns=turns15, telephony=leg(16)), HERE / "15_escalation_late.json")

# ---- 16_abandoned: caller_hangup mid unfinished slot-fill; no farewell; no terminal success ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=3000,
          llm=[llm("l0", "openai/gpt-5-mini", "slot_fill", "order_number",
                   ["order_number"], "Can I get your order number?", 600, 15)],
          tts=[tts("t0", "Can I get your order number?", 29, 1.9)],
          playback=[playback("p0", 29, 1.9)])
dump(Trace(conversation=conv(cid(16), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(3)), HERE / "16_abandoned.json")

# ---- 17_false_resolve: agent asserts completion, but mutation tool result indicates failure ----
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=4000,
          tools=[tool("tool0", "process_refund", "sha256:refundargs1", "mutation",
                      result_hash="sha256:refund_failed_rollback_9f2")],
          llm=[llm("l0", "openai/gpt-5-mini", "compose", "confirm_refund",
                   ["confirm_refund"], "Your refund is processed. Anything else?",
                   700, 20)],
          tts=[tts("t0", "Your refund is processed. Anything else?", 41, 2.6)],
          playback=[playback("p0", 41, 2.6)])
dump(Trace(conversation=conv(cid(17), "refund", "caller_hangup"),
           turns=[t0], telephony=leg(4)), HERE / "17_false_resolve.json")

# ---- 18_edge_single_turn: exactly one turn, RESOLVED, minimal spans ----
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=2000,
          llm=[llm("l0", "openai/gpt-5-mini", "compose", "quick_answer",
                   ["quick_answer"], "Your balance is zero.", 400, 12)],
          tts=[tts("t0", "Your balance is zero.", 22, 1.4)],
          playback=[playback("p0", 22, 1.4)])
dump(Trace(conversation=conv(cid(18), "balance_check", "caller_hangup"),
           turns=[t0], telephony=leg(2)), HERE / "18_edge_single_turn.json")

# ---- 19_edge_40_turn: 40 turns, RESOLVED, no waste (scaling edge) ----
turns19 = []
for i in range(40):
    start = i * 2000
    turns19.append(Turn(
        turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
        wall_start_ms=start, wall_end_ms=start + 2000,
        llm=[llm(f"l{i}", "openai/gpt-5-mini", "compose", f"step_{i}",
                 [f"step_{i}"], f"Okay, step {i} done.", 500, 15)],
        tts=[tts(f"t{i}", f"Okay, step {i} done.", 18, 1.2)],
        playback=[playback(f"p{i}", 18, 1.2)]))
dump(Trace(conversation=conv(cid(19), "long_technical_support", "caller_hangup"),
           turns=turns19, telephony=leg(80)), HERE / "19_edge_40_turn.json")

print("wrote fixtures 01-06, 08-19")
