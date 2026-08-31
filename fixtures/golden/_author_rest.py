# fixtures/golden/_author_rest.py  (run once to emit fixtures 01-06, 08-19)
import math
from pathlib import Path
from _builder import conv, llm, tts, playback, tool, leg, context, asr, stack, dump
from turnstile_schema import Trace, Turn, ToolCall

HERE = Path(__file__).parent


def cid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def billable(final_ms):
    """Round the conversation's last active millisecond up to whole billed seconds."""
    return math.ceil(final_ms / 1000)


def inflate_turns(n, start_cursor, index_offset=0):
    """n sequential filler turns (llm -> tts -> playback), back to back."""
    ts = []
    cursor = start_cursor
    for j in range(n):
        i = j + index_offset
        turn_start = cursor
        l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                           kind="compose", chosen=f"step_{i}", candidates=[f"step_{i}"],
                           out_text=f"Okay, checking step {i}.", in_tok=500 + i * 5,
                           out_tok=15)
        t, cursor = stack(cursor, tts, span_id=f"t{i}", text=f"Okay, checking step {i}.",
                           chars=20, secs=1.3)
        p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=20, secs=1.3)
        ts.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                        wall_start_ms=turn_start, wall_end_ms=cursor,
                        llm=[l], tts=[t], playback=[p]))
    return ts, cursor


def escalation_turns(no_return_idx, total_turns, start_cursor, escalate_kind="escalate_check"):
    """Filler turns, one escalate_check turn at no_return_idx, a successful
    (effect=committed) handoff on the final turn. Sequential, back to back."""
    ts = []
    cursor = start_cursor
    for i in range(total_turns):
        turn_start = cursor
        if i == no_return_idx:
            l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                               kind=escalate_kind, chosen="escalate",
                               candidates=["resolve", "escalate"],
                               out_text="This needs a human.", in_tok=700, out_tok=20,
                               latency=700)
            t, cursor = stack(cursor, tts, span_id=f"t{i}", text="This needs a human.",
                               chars=19, secs=1.3)
            p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=19, secs=1.3)
            ts.append(Turn(turn_index=i, speaker_first="caller",
                            wall_start_ms=turn_start, wall_end_ms=cursor,
                            llm=[l], tts=[t], playback=[p]))
        elif i == total_turns - 1:
            tool_span, cursor = stack(cursor, tool, span_id=f"tool{i}",
                                       name="transfer_to_agent",
                                       args_hash=f"sha256:xfer{i}", kind="handoff",
                                       effect="committed")
            l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                               kind="compose", chosen="transfer", candidates=["transfer"],
                               out_text="Transferring you now.", in_tok=650, out_tok=18)
            t, cursor = stack(cursor, tts, span_id=f"t{i}", text="Transferring you now.",
                               chars=22, secs=1.5)
            p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=22, secs=1.5)
            ts.append(Turn(turn_index=i, speaker_first="agent",
                            wall_start_ms=turn_start, wall_end_ms=cursor,
                            tools=[tool_span], llm=[l], tts=[t], playback=[p]))
        else:
            l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                               kind="compose", chosen=f"stall_{i}", candidates=[f"stall_{i}"],
                               out_text="Let me keep looking into this.", in_tok=600,
                               out_tok=16)
            t, cursor = stack(cursor, tts, span_id=f"t{i}",
                               text="Let me keep looking into this.", chars=28, secs=1.8)
            p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=28, secs=1.8)
            ts.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                            wall_start_ms=turn_start, wall_end_ms=cursor,
                            llm=[l], tts=[t], playback=[p]))
    return ts, cursor


# ---- 01_over_model: frontier gpt-5 used for a route decision, output_tokens<32 ----
l0, cursor = stack(0, llm, span_id="l0", model="gpt-5", kind="route",
                    chosen="order_status", candidates=["order_status", "billing"],
                    out_text="Order status.", in_tok=500, out_tok=15)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="Order status.", chars=13, secs=1.0)
p0, cursor = stack(cursor, playback, span_id="p0", chars=13, secs=1.0)
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=cursor,
          llm=[l0], tts=[t0_tts], playback=[p0])
dump(Trace(conversation=conv(cid(1), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(billable(cursor))), HERE / "01_over_model.json")

# ---- 02_context_bloat: input_tokens rises >400/turn across 5 turns, cache_read always 0 ----
in_toks = [800, 1300, 1900, 2600, 3400]
turns02 = []
cursor = 0
for i, tok in enumerate(in_toks):
    turn_start = cursor
    l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                       kind="compose", chosen="continue", candidates=["continue"],
                       out_text=f"Response {i}.", in_tok=tok, out_tok=20, cache_read=0)
    t, cursor = stack(cursor, tts, span_id=f"t{i}", text=f"Response {i}.", chars=12, secs=1.0)
    p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=12, secs=1.0)
    turns02.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                         wall_start_ms=turn_start, wall_end_ms=cursor,
                         llm=[l], tts=[t], playback=[p]))
dump(Trace(conversation=conv(cid(2), "billing_dispute", "caller_hangup"),
           turns=turns02, telephony=leg(billable(cursor))), HERE / "02_context_bloat.json")

# ---- 03_redundant_retrieval: tool.call(retrieval) re-fetches a doc already in an
#      earlier turn's context.assemble.retrieved_doc_ids ----
DOC_ID = "doc_refund_policy_7"
cursor = 0
turn0_start = cursor
c0, cursor = stack(cursor, context, span_id="c0", context_tokens=900, history_tokens=200,
                    system_tokens=100, retrieved_tokens=600, retrieved_doc_ids=[DOC_ID])
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="route",
                    chosen="refund", candidates=["refund", "order_status"],
                    out_text="Let me look into that.", in_tok=700, out_tok=18)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="Let me look into that.",
                        chars=22, secs=1.5)
p0, cursor = stack(cursor, playback, span_id="p0", chars=22, secs=1.5)
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=turn0_start, wall_end_ms=cursor,
          context=c0, llm=[l0], tts=[t0_tts], playback=[p0])

turn1_start = cursor
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5-mini", kind="slot_fill",
                    chosen="order_number", candidates=["order_number"],
                    out_text="What is your order number?", in_tok=750, out_tok=14)
t1_tts, cursor = stack(cursor, tts, span_id="t1", text="What is your order number?",
                        chars=27, secs=1.8)
p1, cursor = stack(cursor, playback, span_id="p1", chars=27, secs=1.8)
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start, wall_end_ms=cursor,
          llm=[l1], tts=[t1_tts], playback=[p1])

turn2_start = cursor
redundant_tool = ToolCall.model_validate({
    "span_id": "tool2",
    "turnstile.start_offset_ms": cursor, "turnstile.duration_ms": 400,
    "turnstile.tool_name": "search_kb",
    "turnstile.args_hash": "sha256:kbq1",
    "turnstile.args_json": f'{{"query": "refund policy", "doc_id": "{DOC_ID}"}}',
    "turnstile.result_hash": "sha256:kbr1", "turnstile.latency_ms": 400,
    "turnstile.tool_kind": "retrieval"})
cursor += redundant_tool.duration_ms
l2, cursor = stack(cursor, llm, span_id="l2", model="gpt-5-mini", kind="compose",
                    chosen="explain_refund", candidates=["explain_refund"],
                    out_text="Here is our refund policy again.", in_tok=800, out_tok=25)
t2_tts, cursor = stack(cursor, tts, span_id="t2", text="Here is our refund policy again.",
                        chars=33, secs=2.1)
p2, cursor = stack(cursor, playback, span_id="p2", chars=33, secs=2.1)
t2 = Turn(turn_index=2, speaker_first="agent", wall_start_ms=turn2_start, wall_end_ms=cursor,
          tools=[redundant_tool], llm=[l2], tts=[t2_tts], playback=[p2])
dump(Trace(conversation=conv(cid(3), "refund", "caller_hangup"),
           turns=[t0, t1, t2], telephony=leg(billable(cursor))),
     HERE / "03_redundant_retrieval.json")

# ---- 04_turn_inflation: 14 turns for order_status (baseline p50=8), RESOLVED-ending ----
turns04, cursor = inflate_turns(14, 0)
dump(Trace(conversation=conv(cid(4), "order_status", "caller_hangup"),
           turns=turns04, telephony=leg(billable(cursor))), HERE / "04_turn_inflation.json")

# ---- 05_reprompt_loop: same slot_fill decision_chosen twice, consecutive turns, no fill between ----
cursor = 0
turn0_start = cursor
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="slot_fill",
                    chosen="phone_number", candidates=["phone_number"],
                    out_text="What's your phone number?", in_tok=600, out_tok=16)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="What's your phone number?",
                        chars=27, secs=1.7)
p0, cursor = stack(cursor, playback, span_id="p0", chars=27, secs=1.7)
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=turn0_start, wall_end_ms=cursor,
          llm=[l0], tts=[t0_tts], playback=[p0])

turn1_start = cursor
a1, cursor = stack(cursor, asr, span_id="a1", transcript="uhh sorry what", audio_seconds=1.2)
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5-mini", kind="slot_fill",
                    chosen="phone_number", candidates=["phone_number"],
                    out_text="Sorry, could you repeat your phone number?", in_tok=650,
                    out_tok=17)
t1_tts, cursor = stack(cursor, tts, span_id="t1",
                        text="Sorry, could you repeat your phone number?", chars=44, secs=2.5)
p1, cursor = stack(cursor, playback, span_id="p1", chars=44, secs=2.5)
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start, wall_end_ms=cursor,
          asr=[a1], llm=[l1], tts=[t1_tts], playback=[p1])
dump(Trace(conversation=conv(cid(5), "account_update", "caller_hangup"),
           turns=[t0, t1], telephony=leg(billable(cursor))), HERE / "05_reprompt_loop.json")

# ---- 06_dead_tokens: llm output_text with no matching tts.synthesize in the turn ----
l0, cursor = stack(0, llm, span_id="l0", model="gpt-5-mini", kind="compose",
                    chosen="internal_note", candidates=["internal_note"],
                    out_text="Here is extra info nobody hears.", in_tok=500, out_tok=22)
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=cursor, llm=[l0])
dump(Trace(conversation=conv(cid(6), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(billable(cursor))), HERE / "06_dead_tokens.json")

# ---- 08_silence_tax: turn wall span far exceeds sum of child-span durations (>200ms gap),
#      meter (telephony) still running, no playback covering the gap ----
tool0, cursor = stack(0, tool, span_id="tool0", name="lookup_order", args_hash="sha256:lk1",
                       kind="lookup", latency=300)
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="compose",
                    chosen="report_status", candidates=["report_status"],
                    out_text="Checking now.", in_tok=600, out_tok=14, latency=500)
# active span extent = 300 + 500 = 800ms; turn wall is held open to 6000ms -- 5200ms of
# dead air (>200ms) with the telephony meter still running.
WALL_END_08 = 6000
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=WALL_END_08,
          tools=[tool0], llm=[l0])
dump(Trace(conversation=conv(cid(8), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(billable(WALL_END_08))), HERE / "08_silence_tax.json")

# ---- 09_escalation_debt: escalation implied at turn 3, handoff 9 turns later (turn 12) ----
turns09, cursor = escalation_turns(no_return_idx=3, total_turns=13, start_cursor=0)
dump(Trace(conversation=conv(cid(9), "billing_dispute", "escalated"),
           turns=turns09, telephony=leg(billable(cursor))), HERE / "09_escalation_debt.json")

# ---- 10_tool_thrash: two tool.call spans, same tool_name, identical args_hash;
#      both calls actually succeeded (effect=committed) -- the waste is the redundant
#      second call, not a failed first one. ----
cursor = 0
turn0_start = cursor
tool0, cursor = stack(cursor, tool, span_id="tool0", name="update_address",
                       args_hash="sha256:dupAddr1", kind="mutation",
                       result_hash="sha256:updok1", effect="committed")
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="compose",
                    chosen="confirm_update", candidates=["confirm_update"],
                    out_text="Updating your address.", in_tok=500, out_tok=14)
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=turn0_start, wall_end_ms=cursor,
          tools=[tool0], llm=[l0])

turn1_start = cursor
tool1, cursor = stack(cursor, tool, span_id="tool1", name="update_address",
                       args_hash="sha256:dupAddr1", kind="mutation",
                       result_hash="sha256:updok1", effect="committed")
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5-mini", kind="compose",
                    chosen="confirm_update_retry", candidates=["confirm_update_retry"],
                    out_text="Trying that update again.", in_tok=520, out_tok=15)
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start, wall_end_ms=cursor,
          tools=[tool1], llm=[l1])
dump(Trace(conversation=conv(cid(10), "account_update", "caller_hangup"),
           turns=[t0, t1], telephony=leg(billable(cursor))), HERE / "10_tool_thrash.json")

# ---- 11_multi_waste_a: over_model(01) + context_bloat(02) + silence_tax(08) ----
in_toks_11 = [800, 1300, 1900, 2600, 3400]
turns11 = []
l0, cursor = stack(0, llm, span_id="l0", model="gpt-5", kind="route",
                    chosen="handle_billing", candidates=["handle_billing"],
                    out_text="Response 0.", in_tok=in_toks_11[0], out_tok=15, latency=500,
                    cache_read=0)
# turn 0: zero tts/playback spans despite a 5000ms billed wall span -- identical in
# kind to 08_silence_tax's clean D8 encoding (total audio silence for a billed turn),
# not a wall-minus-latency arithmetic gap.
WALL_END_11_T0 = 5000
turns11.append(Turn(turn_index=0, speaker_first="caller", wall_start_ms=0,
                     wall_end_ms=WALL_END_11_T0, llm=[l0]))
cursor = WALL_END_11_T0
for i, tok in list(enumerate(in_toks_11))[1:]:
    turn_start = cursor
    l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                       kind="compose", chosen="handle_billing",
                       candidates=["handle_billing"], out_text=f"Response {i}.",
                       in_tok=tok, out_tok=20, latency=500, cache_read=0)
    t, cursor = stack(cursor, tts, span_id=f"t{i}", text=f"Response {i}.", chars=12, secs=1.0)
    p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=12, secs=1.0)
    turns11.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                         wall_start_ms=turn_start, wall_end_ms=cursor,
                         llm=[l], tts=[t], playback=[p]))
dump(Trace(conversation=conv(cid(11), "billing_dispute", "caller_hangup"),
           turns=turns11, telephony=leg(billable(cursor))), HERE / "11_multi_waste_a.json")

# ---- 12_multi_waste_b: dead_tokens(06) + barge_in(07) + tool_thrash(10) ----
cursor = 0
turn0_start = cursor
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="compose",
                    chosen="internal_note", candidates=["internal_note"],
                    out_text="Here is extra info nobody hears.", in_tok=500, out_tok=22)
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=turn0_start, wall_end_ms=cursor,
          llm=[l0])

turn1_start = cursor
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5", kind="compose",
                    chosen="long_explanation", candidates=["long_explanation"],
                    out_text="Here is a very long explanation of our refund policy ...",
                    in_tok=1200, out_tok=140)
t1_tts, cursor = stack(cursor, tts, span_id="t1",
                        text="Here is a very long explanation of our refund policy "
                             "that continues well past where the caller interrupts.",
                        chars=184, secs=11.2)
p1, cursor = stack(cursor, playback, span_id="p1", chars=61, secs=3.8, truncated_by="barge_in")
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start, wall_end_ms=cursor,
          barge_in=True, llm=[l1], tts=[t1_tts], playback=[p1])

turn2_start = cursor
tool2, cursor = stack(cursor, tool, span_id="tool2", name="update_address",
                       args_hash="sha256:dupAddr9", kind="mutation",
                       result_hash="sha256:updok9", effect="committed")
l2, cursor = stack(cursor, llm, span_id="l2", model="gpt-5-mini", kind="compose",
                    chosen="confirm_update", candidates=["confirm_update"],
                    out_text="Updating your address.", in_tok=500, out_tok=14)
t2 = Turn(turn_index=2, speaker_first="agent", wall_start_ms=turn2_start, wall_end_ms=cursor,
          tools=[tool2], llm=[l2])

turn3_start = cursor
tool3, cursor = stack(cursor, tool, span_id="tool3", name="update_address",
                       args_hash="sha256:dupAddr9", kind="mutation",
                       result_hash="sha256:updok9", effect="committed")
l3, cursor = stack(cursor, llm, span_id="l3", model="gpt-5-mini", kind="compose",
                    chosen="confirm_update_retry", candidates=["confirm_update_retry"],
                    out_text="Trying that update again.", in_tok=520, out_tok=15)
t3 = Turn(turn_index=3, speaker_first="agent", wall_start_ms=turn3_start, wall_end_ms=cursor,
          tools=[tool3], llm=[l3])
dump(Trace(conversation=conv(cid(12), "refund", "caller_hangup"),
           turns=[t0, t1, t2, t3], telephony=leg(billable(cursor))),
     HERE / "12_multi_waste_b.json")

# ---- 13_multi_waste_c: redundant_retrieval(03) + turn_inflation(04) + reprompt_loop(05) ----
DOC_ID_13 = "doc_order_faq_3"
turns13 = []
cursor = 0
turn0_start = cursor
c0, cursor = stack(cursor, context, span_id="c0", context_tokens=900, history_tokens=200,
                    system_tokens=100, retrieved_tokens=600, retrieved_doc_ids=[DOC_ID_13])
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="route",
                    chosen="order_status", candidates=["order_status"],
                    out_text="Let me check that.", in_tok=700, out_tok=18)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="Let me check that.", chars=18, secs=1.4)
p0, cursor = stack(cursor, playback, span_id="p0", chars=18, secs=1.4)
turns13.append(Turn(turn_index=0, speaker_first="caller", wall_start_ms=turn0_start,
                     wall_end_ms=cursor, context=c0, llm=[l0], tts=[t0_tts], playback=[p0]))

turn1_start = cursor
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5-mini", kind="slot_fill",
                    chosen="order_number", candidates=["order_number"],
                    out_text="What is your order number?", in_tok=750, out_tok=14)
t1_tts, cursor = stack(cursor, tts, span_id="t1", text="What is your order number?",
                        chars=27, secs=1.8)
p1, cursor = stack(cursor, playback, span_id="p1", chars=27, secs=1.8)
turns13.append(Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start,
                     wall_end_ms=cursor, llm=[l1], tts=[t1_tts], playback=[p1]))

turn2_start = cursor
l2, cursor = stack(cursor, llm, span_id="l2", model="gpt-5-mini", kind="slot_fill",
                    chosen="order_number", candidates=["order_number"],
                    out_text="Sorry, could you repeat your order number?", in_tok=770,
                    out_tok=16)
t2_tts, cursor = stack(cursor, tts, span_id="t2",
                        text="Sorry, could you repeat your order number?", chars=43, secs=2.4)
p2, cursor = stack(cursor, playback, span_id="p2", chars=43, secs=2.4)
turns13.append(Turn(turn_index=2, speaker_first="agent", wall_start_ms=turn2_start,
                     wall_end_ms=cursor, llm=[l2], tts=[t2_tts], playback=[p2]))

turn3_start = cursor
redundant_tool_13 = ToolCall.model_validate({
    "span_id": "tool3",
    "turnstile.start_offset_ms": cursor, "turnstile.duration_ms": 400,
    "turnstile.tool_name": "search_kb",
    "turnstile.args_hash": "sha256:kbq2",
    "turnstile.args_json": f'{{"query": "order faq", "doc_id": "{DOC_ID_13}"}}',
    "turnstile.result_hash": "sha256:kbr2", "turnstile.latency_ms": 400,
    "turnstile.tool_kind": "retrieval"})
cursor += redundant_tool_13.duration_ms
l3, cursor = stack(cursor, llm, span_id="l3", model="gpt-5-mini", kind="compose",
                    chosen="explain_order", candidates=["explain_order"],
                    out_text="Here is our order FAQ again.", in_tok=800, out_tok=24)
t3_tts, cursor = stack(cursor, tts, span_id="t3", text="Here is our order FAQ again.",
                        chars=30, secs=2.0)
p3, cursor = stack(cursor, playback, span_id="p3", chars=30, secs=2.0)
turns13.append(Turn(turn_index=3, speaker_first="agent", wall_start_ms=turn3_start,
                     wall_end_ms=cursor, tools=[redundant_tool_13], llm=[l3], tts=[t3_tts],
                     playback=[p3]))

# pad out to 14 turns total for turn_inflation (04)
pad_turns, cursor = inflate_turns(10, cursor, index_offset=4)
turns13.extend(pad_turns)
dump(Trace(conversation=conv(cid(13), "order_status", "caller_hangup"),
           turns=turns13, telephony=leg(billable(cursor))), HERE / "13_multi_waste_c.json")

# ---- 14_escalation_early: escalation implied at turn 3 == final turn == handoff (debt=0) ----
turns14 = []
cursor = 0
for i in range(3):
    turn_start = cursor
    l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini", kind="compose",
                       chosen=f"try_{i}", candidates=[f"try_{i}"],
                       out_text="Let me try to help with that.", in_tok=550, out_tok=16)
    t, cursor = stack(cursor, tts, span_id=f"t{i}", text="Let me try to help with that.",
                       chars=27, secs=1.8)
    p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=27, secs=1.8)
    turns14.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                         wall_start_ms=turn_start, wall_end_ms=cursor,
                         llm=[l], tts=[t], playback=[p]))
turn3_start = cursor
tool3, cursor = stack(cursor, tool, span_id="tool3", name="transfer_to_agent",
                       args_hash="sha256:xfer3", kind="handoff", effect="committed")
l3, cursor = stack(cursor, llm, span_id="l3", model="gpt-5-mini",
                    kind="escalate_check", chosen="escalate", candidates=["resolve", "escalate"],
                    out_text="Transferring you to a specialist now.", in_tok=700, out_tok=20)
t3_tts, cursor = stack(cursor, tts, span_id="t3", text="Transferring you to a specialist now.",
                        chars=39, secs=2.4)
p3, cursor = stack(cursor, playback, span_id="p3", chars=39, secs=2.4)
turns14.append(Turn(turn_index=3, speaker_first="caller", wall_start_ms=turn3_start,
                     wall_end_ms=cursor, tools=[tool3], llm=[l3], tts=[t3_tts],
                     playback=[p3]))
dump(Trace(conversation=conv(cid(14), "billing_dispute", "escalated"),
           turns=turns14, telephony=leg(billable(cursor))), HERE / "14_escalation_early.json")

# ---- 15_escalation_late: escalation implied at penultimate turn, handoff at final (debt=1) ----
turns15, cursor = escalation_turns(no_return_idx=6, total_turns=8, start_cursor=0,
                                    escalate_kind="escalate_check")
dump(Trace(conversation=conv(cid(15), "billing_dispute", "escalated"),
           turns=turns15, telephony=leg(billable(cursor))), HERE / "15_escalation_late.json")

# ---- 16_abandoned: caller_hangup mid unfinished slot-fill; no farewell; no terminal success ----
l0, cursor = stack(0, llm, span_id="l0", model="gpt-5-mini", kind="slot_fill",
                    chosen="order_number", candidates=["order_number"],
                    out_text="Can I get your order number?", in_tok=600, out_tok=15)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="Can I get your order number?",
                        chars=29, secs=1.9)
p0, cursor = stack(cursor, playback, span_id="p0", chars=29, secs=1.9)
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=cursor,
          llm=[l0], tts=[t0_tts], playback=[p0])
dump(Trace(conversation=conv(cid(16), "order_status", "caller_hangup"),
           turns=[t0], telephony=leg(billable(cursor))), HERE / "16_abandoned.json")

# ---- 17_false_resolve: agent asserts completion, but the mutation's terminal effect
#      is `rejected` -- the call succeeded (tool_status=ok) but the refund did not
#      take. This is the textbook FALSE_RESOLVE the v1.1 effect field exists for. ----
tool0, cursor = stack(0, tool, span_id="tool0", name="process_refund",
                       args_hash="sha256:refundargs1", kind="mutation",
                       result_hash="sha256:refund_failed_rollback_9f2",
                       tool_status="ok", effect="rejected")
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="compose",
                    chosen="confirm_refund", candidates=["confirm_refund"],
                    out_text="Your refund is processed. Anything else?", in_tok=700,
                    out_tok=20)
t0_tts, cursor = stack(cursor, tts, span_id="t0",
                        text="Your refund is processed. Anything else?", chars=41, secs=2.6)
p0, cursor = stack(cursor, playback, span_id="p0", chars=41, secs=2.6)
t0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=cursor,
          tools=[tool0], llm=[l0], tts=[t0_tts], playback=[p0])
dump(Trace(conversation=conv(cid(17), "refund", "caller_hangup"),
           turns=[t0], telephony=leg(billable(cursor))), HERE / "17_false_resolve.json")

# ---- 18_edge_single_turn: exactly one turn, RESOLVED, minimal spans ----
l0, cursor = stack(0, llm, span_id="l0", model="gpt-5-mini", kind="compose",
                    chosen="quick_answer", candidates=["quick_answer"],
                    out_text="Your balance is zero.", in_tok=400, out_tok=12)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="Your balance is zero.",
                        chars=22, secs=1.4)
p0, cursor = stack(cursor, playback, span_id="p0", chars=22, secs=1.4)
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=cursor,
          llm=[l0], tts=[t0_tts], playback=[p0])
dump(Trace(conversation=conv(cid(18), "balance_check", "caller_hangup"),
           turns=[t0], telephony=leg(billable(cursor))), HERE / "18_edge_single_turn.json")

# ---- 19_edge_40_turn: 40 turns, RESOLVED, no waste (scaling edge). Turn 6 also carries
#      overlap shape B for the Detector 8 union proof: its llm.decide starts 400ms
#      before turn 5's audio.playback finishes -- the agent is already deciding the
#      next turn while the caller is still hearing the previous one. ----
turns19 = []
cursor = 0
for i in range(40):
    turn_start = cursor - 400 if i == 6 else cursor
    l, c2 = stack(turn_start, llm, span_id=f"l{i}", model="gpt-5-mini",
                  kind="compose", chosen=f"step_{i}", candidates=[f"step_{i}"],
                  out_text=f"Okay, step {i} done.", in_tok=500, out_tok=15)
    t, c2 = stack(c2, tts, span_id=f"t{i}", text=f"Okay, step {i} done.", chars=18, secs=1.2)
    p, c2 = stack(c2, playback, span_id=f"p{i}", chars=18, secs=1.2)
    turns19.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                         wall_start_ms=turn_start, wall_end_ms=c2, llm=[l], tts=[t],
                         playback=[p]))
    cursor = c2
dump(Trace(conversation=conv(cid(19), "long_technical_support", "caller_hangup"),
           turns=turns19, telephony=leg(billable(cursor))), HERE / "19_edge_40_turn.json")

print("wrote fixtures 01-06, 08-19")

# ==================== effect_edge (v1.1): fixtures 20-22 ====================

# ---- 20_unknown_mutation: a required mutation call times out mid-flight --
#      tool_status=error, effect=unknown. The agent hedges rather than
#      asserting completion; the verdict layer must not fabricate RESOLVED or
#      FALSE_RESOLVE from genuinely ambiguous evidence (confidence capped). ----
cursor = 0
turn0_start = cursor
l0, cursor = stack(cursor, llm, span_id="l0", model="gpt-5-mini", kind="route",
                    chosen="cancel_subscription",
                    candidates=["cancel_subscription", "retain_customer"],
                    out_text="Let me cancel that for you.", in_tok=650, out_tok=16)
t0_tts, cursor = stack(cursor, tts, span_id="t0", text="Let me cancel that for you.",
                        chars=27, secs=1.7)
p0, cursor = stack(cursor, playback, span_id="p0", chars=27, secs=1.7)
turns20 = [Turn(turn_index=0, speaker_first="caller", wall_start_ms=turn0_start,
                 wall_end_ms=cursor, llm=[l0], tts=[t0_tts], playback=[p0])]

turn1_start = cursor
tool1, cursor = stack(cursor, tool, span_id="tool1", name="cancel_subscription",
                       args_hash="sha256:cancelargs1", kind="mutation",
                       result_hash="sha256:timeout_no_response", latency=8000,
                       tool_status="error", effect="unknown")
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5-mini", kind="compose",
                    chosen="hedge_uncertain", candidates=["hedge_uncertain"],
                    out_text="I'm having trouble confirming that went through -- "
                             "I'll flag it for a specialist to verify.", in_tok=680,
                    out_tok=24)
t1_tts, cursor = stack(cursor, tts, span_id="t1",
                        text="I'm having trouble confirming that went through -- "
                             "I'll flag it for a specialist to verify.", chars=88, secs=4.2)
p1, cursor = stack(cursor, playback, span_id="p1", chars=88, secs=4.2)
turns20.append(Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start,
                     wall_end_ms=cursor, tools=[tool1], llm=[l1], tts=[t1_tts],
                     playback=[p1]))
dump(Trace(conversation=conv(cid(20), "cancel_subscription", "caller_hangup"),
           turns=turns20, telephony=leg(billable(cursor))), HERE / "20_unknown_mutation.json")

# ---- 21_handoff_rejected: tool_kind=handoff, effect=rejected -- no agents
#      available. Also exercises Detector 9 tier 2 (spend before a handoff
#      that then FAILS): three filler turns of spend precede the rejected
#      transfer. expected verdict is UNRESOLVED, never ESCALATED -- the
#      caller paid the full conversation cost and is left stranded. ----
turns21 = []
cursor = 0
for i in range(3):
    turn_start = cursor
    l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                       kind="compose", chosen=f"try_{i}", candidates=[f"try_{i}"],
                       out_text="Let me see what I can do about that.", in_tok=560,
                       out_tok=16)
    t, cursor = stack(cursor, tts, span_id=f"t{i}",
                       text="Let me see what I can do about that.", chars=36, secs=2.1)
    p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=36, secs=2.1)
    turns21.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                         wall_start_ms=turn_start, wall_end_ms=cursor,
                         llm=[l], tts=[t], playback=[p]))
turn3_start = cursor
tool3, cursor = stack(cursor, tool, span_id="tool3", name="transfer_to_agent",
                       args_hash="sha256:xfer_rej3", kind="handoff",
                       result_hash="sha256:no_agents_available",
                       tool_status="ok", effect="rejected")
l3, cursor = stack(cursor, llm, span_id="l3", model="gpt-5-mini",
                    kind="escalate_check", chosen="escalate",
                    candidates=["resolve", "escalate"],
                    out_text="I'm sorry, all our specialists are unavailable right now.",
                    in_tok=690, out_tok=19)
t3_tts, cursor = stack(cursor, tts, span_id="t3",
                        text="I'm sorry, all our specialists are unavailable right now.",
                        chars=58, secs=3.1)
p3, cursor = stack(cursor, playback, span_id="p3", chars=58, secs=3.1)
turns21.append(Turn(turn_index=3, speaker_first="caller", wall_start_ms=turn3_start,
                     wall_end_ms=cursor, tools=[tool3], llm=[l3], tts=[t3_tts],
                     playback=[p3]))
dump(Trace(conversation=conv(cid(21), "billing_dispute", "caller_hangup"),
           turns=turns21, telephony=leg(billable(cursor))), HERE / "21_handoff_rejected.json")

# ---- 22_handoff_pending: tool_kind=handoff, effect=pending -- transfer
#      initiated, caller placed in a queue on hold. Queue time is real; a
#      pending handoff must not be collapsed into ESCALATED (not yet
#      complete) or into a clean, finished outcome. ----
turns22 = []
cursor = 0
for i in range(2):
    turn_start = cursor
    l, cursor = stack(cursor, llm, span_id=f"l{i}", model="gpt-5-mini",
                       kind="compose", chosen=f"try_{i}", candidates=[f"try_{i}"],
                       out_text="Let me look into that for you.", in_tok=540, out_tok=15)
    t, cursor = stack(cursor, tts, span_id=f"t{i}", text="Let me look into that for you.",
                       chars=31, secs=1.9)
    p, cursor = stack(cursor, playback, span_id=f"p{i}", chars=31, secs=1.9)
    turns22.append(Turn(turn_index=i, speaker_first="caller" if i % 2 == 0 else "agent",
                         wall_start_ms=turn_start, wall_end_ms=cursor,
                         llm=[l], tts=[t], playback=[p]))
turn2_start = cursor
tool2, cursor = stack(cursor, tool, span_id="tool2", name="transfer_to_agent",
                       args_hash="sha256:xfer_pend2", kind="handoff",
                       result_hash="sha256:queued_position_4",
                       tool_status="ok", effect="pending")
l2, cursor = stack(cursor, llm, span_id="l2", model="gpt-5-mini",
                    kind="escalate_check", chosen="escalate",
                    candidates=["resolve", "escalate"],
                    out_text="I'm transferring you now -- please hold, you're in the queue.",
                    in_tok=660, out_tok=21)
t2_tts, cursor = stack(cursor, tts, span_id="t2",
                        text="I'm transferring you now -- please hold, you're in the queue.",
                        chars=63, secs=3.4)
p2, cursor = stack(cursor, playback, span_id="p2", chars=63, secs=3.4)
turns22.append(Turn(turn_index=2, speaker_first="caller", wall_start_ms=turn2_start,
                     wall_end_ms=cursor, tools=[tool2], llm=[l2], tts=[t2_tts],
                     playback=[p2]))
dump(Trace(conversation=conv(cid(22), "billing_dispute", "escalated"),
           turns=turns22, telephony=leg(billable(cursor))), HERE / "22_handoff_pending.json")

print("wrote effect_edge fixtures 20-22")
