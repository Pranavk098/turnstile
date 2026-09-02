"""The harness's scripted scenario inputs (brief item 2).

These are AGENT SCRIPTS, not the measurement: the scenario is the interruption-
heavy case where barge-in waste concentrates -- a long confirmation readback
(order/policy details with dollar figures, the kind of utterance contact
centers actually read back). Realism rules from the brief:

* realistic length and content (an order/policy confirmation a human agent
  would genuinely read aloud),
* NO length-tuning to inflate waste -- they are what they are, and D7's
  response is reported as a SWEEP over the modeled barge-in rate, never as a
  single tuned figure.

The caller lines are scripted model inputs too (the harness does no ASR):
each call opens with a caller utterance, and on a sampled barge-in the caller
interrupts with one of the interrupt lines. Their ``audio_seconds`` in the
recorded trace is a STATED modeled duration, not a measurement.
"""
from __future__ import annotations

SCENARIO_ID = "confirmation_readback"

# Agent readback utterances: long confirmation texts (the D7-concentrating case).
READBACKS: list[str] = [
    (
        "Let me confirm your order: one large pepperoni pizza, a side of garlic "
        "knots, and two medium soft drinks. Your total comes to twenty three "
        "dollars and fifty cents, and that includes the delivery fee. Is that "
        "all correct?"
    ),
    (
        "So I have your booking as two adults, checking in on the fourteenth of "
        "this month, checking out on the twentieth, one king room with an ocean "
        "view, breakfast included, at one hundred eighty nine dollars per night "
        "before taxes. Shall I confirm those dates?"
    ),
    (
        "Reading back your policy details: comprehensive coverage, five hundred "
        "dollar deductible, roadside assistance included, and the named drivers "
        "are yourself and one additional driver. The annual premium is one "
        "thousand one hundred and forty dollars. Would you like me to go ahead "
        "and bind that policy now?"
    ),
    (
        "Here is what I show on your account: the renewal date is the first of "
        "next month, the plan is the family tier at forty nine ninety nine per "
        "month, and the payment method on file is the card ending in four four "
        "one seven. Do you want me to update anything before the renewal runs?"
    ),
    (
        "Let me read back the appointment: Thursday the ninth at two thirty in "
        "the afternoon, at the Riverside branch, with a service advisor for the "
        "brake inspection you requested. You will get a text reminder the day "
        "before. Does that time still work for you?"
    ),
    (
        "To confirm your flight change: departing on the sixth at seven fifteen "
        "in the morning, returning on the thirteenth at nine forty at night, "
        "one checked bag added, seat selection included, and the change fee is "
        "seventy five dollars which will appear on your card. Should I ticket "
        "this itinerary?"
    ),
    (
        "I have your return as: one pair of running shoes in size ten, reason "
        "code sizing, refund to the original payment method, and because you "
        "are inside the thirty day window there is no return charge. The refund "
        "is eighty four dollars and twenty cents. Do you want me to email you "
        "the label now?"
    ),
    (
        "Confirming the installation visit: a technician between eight and noon "
        "on Saturday, the broadband package at three hundred megabits, the "
        "router rental at five dollars a month, and a one time activation fee "
        "of thirty five dollars on your first bill. Everything look right to "
        "you?"
    ),
]

# Caller opening (turn 0) and interrupt lines: scripted MODEL INPUTS.
CALLER_OPENINGS: list[str] = [
    "Hi, I'd like to double check my order before you send it off.",
    "Yes, can you read that back to me one more time, please?",
    "Sure, go ahead and confirm the details with me.",
]

CALLER_INTERRUPTS: list[str] = [
    "Wait, stop -- that total is wrong.",
    "Sorry, hold on, that's not what I ordered.",
    "No no, hang on, change the date on that.",
    "Wait wait, that address is out of date.",
]
