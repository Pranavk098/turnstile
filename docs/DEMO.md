# Turnstile — four-minute demo script

Built on PRD Appendix A. The through-line: **this is a measurement instrument
that refuses to overstate.** That refusal is the product — so the demo is
explicitly split into two tiers, labeled on the slide, and never blurs them.

## The two tiers (state this structure out loud)

**Tier 1 — measured.** The replay experiment: n≥200 synthetic traces, **real**
model calls through a real backend, real Δcost, real outcome-preservation,
bootstrap CI, divergence rate. Every number in this tier came from a machine
running the thing, not from an author. **This is the headline.** A smaller
router that actually mis-routes 4% of the time shows up here as 4% — the claim
survives scrutiny.

**Tier 2 — instrumented, not measured.** The voice-stack cost decomposition
(ASR/TTS/telephony), and Detectors 7 (barge-in) and 8 (silence tax). On a
synthetic corpus these measure the *generator's* modeled acoustics, not a real
audio pipeline. So we demonstrate the **mechanism** and **do not claim the
magnitude.** Present Tier 2 as a *question*, not a result (see 0:45).

**The promotion line — say it:** "The instrument doesn't change; only the
fidelity of what it's pointed at. The moment the recorder emits real audio,
every Tier-2 detector promotes to Tier 1 with no code change." (This is why
the G2 gate stays live — see `docs/GATES.md`.)

## The spine (PRD Appendix A), tagged by tier

1. **0:00 — one call, cost flame graph.** "This call cost $X; here is where it went." Label the LLM stage **[measured]** and the ASR/TTS/telephony stages **[modeled acoustics]**. Don't let the flame graph imply the audio stages are measured.
2. **0:45 — Detector 7, barge-in — as a QUESTION (Tier 2).** Do NOT assert a cents figure. Say: *"I can't tell you what fraction of your TTS spend your callers never hear — because on synthetic audio I'd only be measuring my own assumptions. I can tell you **nobody is measuring it**, and here is the instrument that would. Do you know your number?"* Then show D7 firing correctly on a trace to prove the mechanism. Handing him the gap beats a figure he can't verify — it's what an FDE does.
3. **1:30 — fleet view (Tier 1).** "Most vendors quote CPRC-naive, the left number. The right one, CPRC-loaded, is your real margin — you pay for the calls that fail too." (Loaded is computed over real replay-verified resolutions.)
4. **2:15 — Detector 9, escalation debt (Tier 1 once the verdict fix lands).** "Escalation was predictable at turn 3. We spent nine more turns and $X getting there." And the tier-2 rejected-handoff number: full conversation cost, stranded caller.
5. **3:00 — replay evidence (THE Tier-1 headline).** "We didn't *suggest* the cheaper router. We replayed N calls on it: X% identical outcome, Y% cheaper, bootstrap CI here, and these Z forked — here they are." Every number machine-produced.
6. **3:40 — limitations, unprompted (below).**

## The two judgment lines — say these out loud (Tier 1: real logic on real replay)

These are what make a CTO believe the number instead of the pitch.

> **On failed handoffs:** "A rejected handoff — no agent available, caller
> stranded after paying for the whole call — is the worst outcome in the taxonomy.
> Every vendor counts it as an escalation, a clean hand-off. We don't. Our ledger
> reads the tool's *effect*, so a handoff that didn't complete is `UNRESOLVED`, not
> `ESCALATED`. We refuse to let a stranded caller flatter the containment rate."

> **On declining to fabricate:** "When a required action times out — the refund was
> sent but we never got confirmation — an LLM judge does what LLM judges do: it
> answers anyway. Ours caps its confidence at 0.6 and refuses to call the
> conversation resolved *or* falsely-resolved, because it genuinely doesn't know.
> The judge declining to answer when the evidence is ambiguous is the whole reason
> you can trust the dollar figures above it."

## Detector 8 as a hypothesis, not a claim (weave into ~1:00)

On the synthetic corpus, **silence tax is 82% of all findings** — D8 dominates.
Do NOT present that as a measurement. Present it as a question the CTO is
uniquely positioned to answer:

> "On modeled acoustics, silence dominates. I don't know if that holds on your
> traffic — my dead-air distribution is an assumption, not a measurement. But if
> it's even directionally right, the most expensive thing your voice agents do is
> make callers *wait*, and nobody is line-iteming it. Do you know your number?"

Then show the **sensitivity sweep**: D8's share as a function of the single
named silence-gap parameter across a plausible range. That converts 82% from a
claimed fact into a stated function of an input — the honest version of a tidy
chart. (Same treatment as the barge-in rate for D7.)

## Limitations to state before you're asked (3:40)

- **The tier split itself:** LLM-layer numbers are measured; ASR/TTS/telephony and D7/D8 magnitudes are modeled on synthetic acoustics. Stated up front, not extracted under questioning.
- **D7 and D8 magnitudes are functions of inputs, not facts:** barge-in rate (D7) and silence-gap distribution (D8) are single named generator parameters; we show each detector's cost across a plausible range rather than claiming one number.
- **Detector 8** on synthetic data is a demo of the detector, not a measurement, until the recorder emits real concurrency (`docs/GATES.md` G1) — over-reports silence on non-overlapping traces. Its 82% corpus dominance is the correct consequence of a modeled silence distribution × a real telephony rate — not a bug, and deliberately *not* calibrated down to a nicer number.
- **Corpus coverage gap (D2, D6):** two of ten classes have fixture-level mechanism demos but **no corpus incidence**, because the generator's context and output-routing behavior doesn't produce them. This is a limitation of the *corpus*, not the instrument. The generator was deliberately NOT re-tuned after seeing detector output (that ordering is tuning-for-detectors in disguise).
- Synthetic traffic finds and quantifies these waste classes; it does not prove any specific fleet's number.
- Verdict confidence priors are fixed, not yet calibrated against 60 hand labels (corpus stage).

## Numbers to have memorized (PRD Appendix B)

Corpus size · scenario count · verdict κ + ECE · replay divergence rate ·
outcome-preservation per variant · CPRC_loaded and its decomposition · largest
single recoverable line item · one annualized figure with assumptions stated aloud.
