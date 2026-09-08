# Brief — C: live conversational agent + open-loop preservation (PHASED, spike-first)

**Base:** `wave0-foundation` @ current tip. Branch prefix `opencode/live-*` (one branch
per phase). Reviewed + merged by Claude. **This is a multi-week, environment-heavy
effort — do it in phases, STOP for an owner go after each, never run ahead.**

## What C is for (two payoffs)
1. **The "point it at a live call" demo:** a real-time voice agent (STT → LLM → tools →
   TTS) whose calls Turnstile ingests and profiles live.
2. **The real (not modeled) preservation-under-divergence number:** open-loop execution
   — actually running a *divergent* decision forward to a terminal state and adjudicating
   the real outcome. This is the honest ceiling the fork oracle only *models* today.

## Global boundaries (hard, all phases)
- **New code lives in a NEW package** (e.g. `packages/live/`). Do NOT modify the existing
  `turnstile_agent` barge-in harness's behavior — it produced the Tier-1 D7 number and is
  load-bearing. Reuse it (Piper synthesis) by import, never by edit.
- **NEVER touch** `packages/schema/`, `fixtures/golden/`, `docs/METHOD.md`,
  `docs/LIMITATIONS.md`. Output is the ingest format (`docs/INGEST.md`) — no schema change.
- **Credit is owner-gated per phase.** Real STT/LLM/TTS calls cost money and add latency;
  every paid phase (2+) is a separate explicit owner yes. Phases 0–1 must run FREE
  (mock/local) or they are mis-scoped.
- **The WSL2/Pipecat environment is a real dependency.** Document every install step,
  version, and device/GPU/audio caveat in `docs/LIVE-AGENT.md` as you go, so it is
  reproducible. If the environment cannot be made to work headless, STOP and flag — do
  not paper over it.
- Any committed Python is green + `ruff check packages/` clean. The live loop itself is
  integration/manual-tested; unit-test everything that can be (trace emission, adapters).

## Phase 0 — environment spike (FREE; STOP and report before Phase 1)
Prove the environment before building anything Turnstile-specific.
- Stand up **Pipecat** in **WSL2**: install it and its deps; run Pipecat's own minimal
  example bot (text or local-audio) to confirm the pipeline runs headless.
- Deliverable: `docs/LIVE-AGENT.md` recording exactly what was installed (versions),
  how it was run, and every caveat (audio devices, GPU, WSL2 networking, headless).
  A one-paragraph go/no-go: is this environment viable for phases 1–3?
- **NO Turnstile integration, no paid calls.** STOP for owner go.

## Phase 1 — text-mode agent → Turnstile (FREE; the integration proof)
A minimal agent **loop without audio**: scripted caller turns in, a decision policy
(MOCK LLM by default — deterministic, free; real LLM behind the owner-gated flag),
mock tools, and it **emits an ingest-format call** (`docs/INGEST.md`) that
`turnstile_ingest` prices / adjudicates / detects and the dashboard renders.
- Proves the agent → Turnstile pipeline closes end-to-end with zero schema change.
- Deliverable: run a scripted conversation, get a valid ingest call, show it in the
  dashboard. Unit-tested trace emission. STOP for owner go.

## Phase 2 — real-time voice (OWNER-GATED paid; the live demo)
Wire real **STT** (caller audio → text) and **TTS** (reuse `turnstile_agent`'s Piper
synthesis) into the Pipecat loop, so a real spoken conversation produces an ingest call.
This is the "live call" walkthrough.
- Owner-gated: real STT/LLM cost credit. Keep the text-mode (Phase 1) path working and
  free. Deliverable: one real spoken call → an ingest call → the dashboard. STOP for owner go.

## Phase 3 — open-loop preservation (OWNER-GATED paid; the real measurement, HARD)
The deep payoff, and its own design. Hook the replay path so a **divergent** decision
(the cheaper model decides differently) is **executed forward** through the live tool
layer to a terminal state, then adjudicated — yielding a **measured** (not modeled)
outcome-preservation-under-divergence number.
- This needs the tool layer to respond to an *arbitrary* decision (a live or simulated
  tool oracle). Design it explicitly and get owner sign-off on the methodology BEFORE
  spending: what "the divergent path resolved" means, how the tool oracle answers, how
  many calls, the honest label. Deliverable: a measured number with stated method, kept
  SEPARATE from and never folded into the modeled figure or the measured-0.985.

## Acceptance (per phase, not all at once)
- P0: environment proven + documented + go/no-go.
- P1: scripted conversation → valid ingest call → dashboard; trace emission unit-tested;
  free.
- P2: one real spoken call → ingest call → dashboard.
- P3: a measured preservation-under-divergence number with methodology, owner-approved
  before the spend, reported separately from the modeled/measured figures.
- Every phase: new package only; agent barge-in harness untouched; schema/golden/METHOD
  untouched; committed code green + ruff clean; `docs/LIVE-AGENT.md` current.
