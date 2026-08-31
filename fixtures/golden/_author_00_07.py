# fixtures/golden/_author_00_07.py  (run once to emit the two JSON files)
import math
from pathlib import Path
from _builder import conv, llm, tts, playback, tool, leg, stack, dump
from turnstile_schema import Trace, Turn

HERE = Path(__file__).parent


def billable(final_ms):
    return math.ceil(final_ms / 1000)


# ---- 00 baseline: clean, resolved, no waste. Turn 0 also carries overlap
# shape A for the Detector 8 union proof: tts.synthesize starts streaming
# 300ms into the still-running llm.decide span (pipelined synthesis, not
# waste), and playback follows once buffered audio is ready. ----
l0 = llm("l0", "gpt-5-mini", "route", "order_status",
         ["order_status", "billing"], "Let me check that.", 600, 12,
         latency=600, start=0)
t0_tts = tts("t0", "Let me check that.", 18, 1.4, start=300)  # 300ms into the 600ms llm span
p0 = playback("p0", 18, 1.4, start=t0_tts.start_offset_ms + t0_tts.duration_ms)
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0,
          wall_end_ms=p0.start_offset_ms + p0.duration_ms,
          llm=[l0], tts=[t0_tts], playback=[p0])
cursor = t0.wall_end_ms

turn1_start = cursor
tool1, cursor = stack(cursor, tool, span_id="tool1", name="lookup_order",
                       args_hash="sha256:a1", kind="lookup")
l1, cursor = stack(cursor, llm, span_id="l1", model="gpt-5-mini",
                    kind="compose", chosen="report_status",
                    candidates=["report_status"], out_text="Your order ships tomorrow.",
                    in_tok=900, out_tok=20, latency=900)
t1_tts, cursor = stack(cursor, tts, span_id="t1", text="Your order ships tomorrow.",
                        chars=26, secs=2.0)
p1, cursor = stack(cursor, playback, span_id="p1", chars=26, secs=2.0)
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=turn1_start,
          wall_end_ms=cursor, tools=[tool1], llm=[l1], tts=[t1_tts], playback=[p1])

turn2_start = cursor
l2, cursor = stack(cursor, llm, span_id="l2", model="gpt-5-mini",
                    kind="compose", chosen="farewell", candidates=["farewell"],
                    out_text="Anything else? Goodbye.", in_tok=700, out_tok=10)
t2_tts, cursor = stack(cursor, tts, span_id="t2", text="Anything else? Goodbye.",
                        chars=23, secs=1.6)
p2, cursor = stack(cursor, playback, span_id="p2", chars=23, secs=1.6)
t2 = Turn(turn_index=2, speaker_first="caller", wall_start_ms=turn2_start,
          wall_end_ms=cursor, llm=[l2], tts=[t2_tts], playback=[p2])

dump(Trace(conversation=conv("00000000-0000-0000-0000-000000000000",
           "order_status", "caller_hangup"), turns=[t0, t1, t2],
           telephony=leg(billable(cursor))), HERE / "00_baseline_clean.json")

# ---- 07 barge-in waste: synthesized >> played, caller interrupted ----
b0_llm, cursor = stack(0, llm, span_id="l0", model="gpt-5", kind="compose",
                        chosen="long_explanation", candidates=["long_explanation"],
                        out_text="Here is a very long explanation of our refund policy ...",
                        in_tok=1200, out_tok=140)
b0_tts, cursor = stack(cursor, tts, span_id="t0",
                        text="Here is a very long explanation of our refund policy "
                             "that continues well past where the caller interrupts.",
                        chars=184, secs=11.2)
# barge-in cuts playback short at 3.8s of the 11.2s synthesized -- duration_ms is
# the actual played extent, not the full synthesized audio.
b0_pb, cursor = stack(cursor, playback, span_id="p0", chars=61, secs=3.8,
                       truncated_by="barge_in")
b0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=cursor,
          barge_in=True, llm=[b0_llm], tts=[b0_tts], playback=[b0_pb])
dump(Trace(conversation=conv("00000000-0000-0000-0000-000000000007",
           "refund", "caller_hangup"), turns=[b0], telephony=leg(billable(cursor))),
     HERE / "07_barge_in_waste.json")
print("wrote 00 and 07")
