# Turnstile — four-minute demo script

Built on PRD Appendix A. The through-line: **this is a measurement instrument
that refuses to overstate.** The two verdict behaviors below are the strongest
thing in the repo — they read as *judgment*, not engineering — so they are
spoken lines, not README footnotes.

## The spine (PRD Appendix A)

1. **0:00 — one call, cost flame graph.** "This call cost $1.34. Here is where it went." (ASR / LLM / TTS / telephony, decomposed.)
2. **0:45 — Detector 7, barge-in.** "Nineteen cents of that was speech we *synthesized and billed* — and the caller interrupted before hearing it. And note: we count only what was actually generated, not the words the engine cancelled. Nobody reports this."
3. **1:30 — fleet view.** "Most vendors quote CPRC-naive, the left number. The right one, CPRC-loaded, is your real margin — you pay for the calls that fail too."
4. **2:15 — Detector 9, escalation debt.** "Escalation was predictable at turn 3. We spent nine more turns and $0.41 getting there."
5. **3:00 — replay evidence.** "We didn't *suggest* the cheaper router. We replayed 340 calls on it: 96.2% identical outcome, 41% cheaper, and here are the thirteen that broke."
6. **3:40 — limitations, unprompted.**

## The two judgment lines — say these out loud

These are what make a CTO believe the number instead of the pitch.

> **On failed handoffs (Rule 5):** "A rejected handoff — no agent available, caller
> stranded after paying for the whole call — is the worst outcome in the taxonomy.
> Every vendor counts it as an escalation, a clean hand-off. We don't. Our ledger
> reads the tool's *effect*, so a handoff that didn't complete is `UNRESOLVED`, not
> `ESCALATED`. We refuse to let a stranded caller flatter the containment rate."

> **On declining to fabricate (Rule 4):** "When a required action times out — the
> refund was sent but we never got confirmation — an LLM judge does what LLM judges
> do: it answers anyway. Ours caps its confidence at 0.6 and refuses to call the
> conversation resolved *or* falsely-resolved, because it genuinely doesn't know.
> The judge declining to answer when the evidence is ambiguous is the whole reason
> you can trust the dollar figures above it."

## Limitations to state before you're asked (3:40)

- Synthetic traffic finds and quantifies these waste classes; it does not prove any specific fleet's number.
- **Detector 8 (silence tax) on fixture data is a demo of the detector, not a measurement, until the recorder emits real concurrency** (see `docs/GATES.md` G1). State the error direction: it over-reports silence on non-overlapping traces.
- Verdict confidence priors are fixed, not yet calibrated against 60 hand labels (that's the corpus stage).

## Numbers to have memorized (PRD Appendix B)

Corpus size · scenario count · verdict κ + ECE · replay divergence rate ·
outcome-preservation per variant · CPRC_loaded and its decomposition · largest
single recoverable line item · one annualized figure with assumptions stated aloud.
