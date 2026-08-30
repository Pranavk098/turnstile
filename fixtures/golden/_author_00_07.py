# fixtures/golden/_author_00_07.py  (run once to emit the two JSON files)
from pathlib import Path
from _builder import conv, llm, tts, playback, tool, leg, dump
from turnstile_schema import Trace, Turn

HERE = Path(__file__).parent

# ---- 00 baseline: clean, resolved, no waste ----
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=4000,
          llm=[llm("l0", "openai/gpt-5-mini", "route", "order_status",
                   ["order_status", "billing"], "Let me check that.", 600, 12)],
          tts=[tts("t0", "Let me check that.", 18, 1.4)],
          playback=[playback("p0", 18, 1.4)])                      # fully played
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=4000, wall_end_ms=8000,
          tools=[tool("tool1", "lookup_order", "sha256:a1", "lookup")],
          llm=[llm("l1", "openai/gpt-5-mini", "compose", "report_status",
                   ["report_status"], "Your order ships tomorrow.", 900, 20)],
          tts=[tts("t1", "Your order ships tomorrow.", 26, 2.0)],
          playback=[playback("p1", 26, 2.0)])
t2 = Turn(turn_index=2, speaker_first="caller", wall_start_ms=8000, wall_end_ms=10000,
          llm=[llm("l2", "openai/gpt-5-mini", "compose", "farewell",
                   ["farewell"], "Anything else? Goodbye.", 700, 10)],
          tts=[tts("t2", "Anything else? Goodbye.", 23, 1.6)],
          playback=[playback("p2", 23, 1.6)])
dump(Trace(conversation=conv("00000000-0000-0000-0000-000000000000",
           "order_status", "caller_hangup"), turns=[t0, t1, t2],
           telephony=leg(10)), HERE / "00_baseline_clean.json")

# ---- 07 barge-in waste: synthesized >> played, caller interrupted ----
b0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=6000,
          barge_in=True,
          llm=[llm("l0", "openai/gpt-5", "compose", "long_explanation",
                   ["long_explanation"],
                   "Here is a very long explanation of our refund policy ...",
                   1200, 140)],
          tts=[tts("t0", "Here is a very long explanation of our refund policy "
                         "that continues well past where the caller interrupts.",
                   184, 11.2)],
          playback=[playback("p0", 61, 3.8, truncated_by="barge_in")])  # 123 chars billed, unheard
dump(Trace(conversation=conv("00000000-0000-0000-0000-000000000007",
           "refund", "caller_hangup"), turns=[b0], telephony=leg(6)),
     HERE / "07_barge_in_waste.json")
print("wrote 00 and 07")
