# Turnstile — four-minute demo script

Built on PRD Appendix A. The through-line: **this is a measurement instrument
that refuses to overstate.** That refusal is the product — so the demo is
explicitly split into two tiers, labeled on the slide, and never blurs them.

## The two tiers (state this structure out loud)

**Tier 1 — proven.** Two numbers, both stand up to a hostile question.

**① The headline — barge-in waste (a number nobody has published).** We ran
**750 real Piper TTS synthesis calls** through the instrument and measured the
fraction of synthesized, *billed* speech a caller never hears when they barge in.
At a cited **15% barge-in rate** and a **2-second streaming buffer**: **~4% of
TTS spend is generated, billed, and never heard** — about one buffer-lead of
audio per interruption (the exact figure is a live Piper measurement, ~4.1% ±
run-to-run timing variance, so we say **~4%**, not a false-precise number). The
mechanism: local streaming TTS generates **~40× realtime** (measured), so the
whole readback exists before the caller has heard a quarter of it; generation
always wins the race — the only question is how far ahead you buffer. **And it's
a fixable number**: chunk the TTS finer and the waste falls — sentence→clause→word
= **~4%→2.3%→1.2%** (measured, real Piper), at a modest synthesis-speed cost
(gen-rate 41×→27×). Swept over barge-in rate 5%→30% = 1.9%→7.9%, and over buffer
policy 0.5s→4s = ~4%→4.7% — with a **floor**: below ~one synthesis chunk you
can't buffer the waste away (TTS commits whole sentences), so it's flat, then
rises. Provenance stated on the slide: real
generation-ahead behavior **measured**; barge-in rate/position **modeled, swept,
uniform-null**; N controlled harness calls, **not production**.

**② The supporting proven number — routing margin.** Deterministic rate arbitrage
on `route` decisions to a cheaper model: **0.57% [0.49, 0.66]** recoverable,
~$126/yr at 1M calls, §8.3-gated, reproducible from the manifest. Exact
arithmetic — small by construction (only `route` is replay-executable today). We
do **not** quote a measured preservation rate: that needs real traffic (Wave-2),
and we won't fake it on synthetic audio. (See `docs/METHOD.md`, `docs/LIMITATIONS.md`.)

**Tier 2 — instrumented, not measured.** The voice-stack cost decomposition
(ASR/TTS/telephony) and **Detector 8 (silence tax)** on synthetic acoustics —
mechanism shown, magnitude not claimed, presented as a *question* (see 0:45).
**Detector 7 (barge-in) has PROMOTED to Tier 1 above** — the native harness
measures its number on real TTS. That promotion is the proof of the next line:

**The promotion line — say it:** "The instrument doesn't change; only the fidelity
of what it's pointed at. D7 just made that jump — a real TTS harness, no code
change to the analysis. D8 follows the moment real audio flows." (This is why the
G2 gate stays live — see `docs/GATES.md`.)

## The spine (PRD Appendix A), tagged by tier

1. **0:00 — one call, cost flame graph.** "This call cost $X; here is where it went." Label the LLM stage **[measured]** and the ASR/TTS/telephony stages **[modeled acoustics]**. Don't let the flame graph imply the audio stages are measured.
2. **0:45 — Detector 7, barge-in — THE measured headline (Tier 1).** Lead with the number nobody has: *"I ran real TTS synthesis and measured how much synthesized, billed speech your callers never hear when they interrupt. At a 15% barge-in rate on a 2-second buffer: **~4% of your TTS spend — generated, billed, and never heard.** Streaming TTS runs ~40× realtime, so the whole readback exists before they've heard a quarter of it. And it's not fixed: chunk the TTS finer and you recover most of it — clause-level **2.3%**, word-level **1.2%** (measured), at a modest synthesis-speed cost."* Show the three sweep tables (barge-in rate 1.9%→7.9%; buffer policy ~4%→4.7%, with a **floor** you can't buffer under — TTS commits whole sentences; and the chunk-granularity remedy sentence→clause→word) as the honesty exhibit, and state the provenance out loud (generation-ahead + per-granularity chars **measured** on real Piper; barge-in rate/position **modeled + swept**; controlled harness, not production, so the headline is **~4%**, not a false-precise figure). This is the reaction you want — not "nice tool," but *"wait, what's OUR number?"*
3. **1:30 — fleet view (Tier 1).** "Most vendors quote CPRC-naive, the left number. The right one, CPRC-loaded, is your real margin — you pay for the calls that fail too." (Loaded is computed over verdict-adjudicated resolutions.)
4. **2:15 — Detector 9, escalation debt (Tier 1 once the verdict fix lands).** "Escalation was predictable at turn 3. We spent nine more turns and $X getting there." And the tier-2 rejected-handoff number: full conversation cost, stranded caller.
5. **3:00 — routing margin, then the ask (Tier 1 supporting → the close).** "And a deterministic one, exact from the rate card: routing eligible `route` decisions to a cheaper model recovers **0.57% [0.49, 0.66]**, ~$126/yr at 1M calls, gated and reproducible from the manifest. Small — it's the *only* remedy replay-executable today; the rest are detected and quantified, not yet replay-proven, and I label them that way. What I am **not** showing you is a preservation rate — that needs real traffic, and I won't fake it on synthetic audio." Then the FDE close, unprompted: *"This is what I can prove on public data and a controlled harness. The barge-in number becomes **yours** the moment you point this at your traffic — your buffer policy, your barge-in rate, your real dollars. That's the engagement."* *(Owner: delivery is yours — the numbers and the honesty lines are fixed.)*
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
