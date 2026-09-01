# Progress & GTM Gap — Turnstile

**Author:** GLM 5.3 (OpenCode), 2026-08-31 · **Branch state:** `wave0-foundation` @ `bb7d0f4` · **Suite:** 545 green
**Companions:** `06-performance-audit.md` (Change B design), `07-full-codebase-audit.md` (validity findings gating the paid run).
**The question this file answers:** how far has this come, what exactly is left, and how far is it from GTM-grade — read as a 0→1 incrementation project, not a stalled one.

---

## 1. The 0→1 ladder — where each stage stands

Turnstile was sequenced from day one as staged increments with hard exit criteria (frozen contracts → instrument → measurement → evidence → demo). Every stage below is *done and hardened*, not "started and abandoned." That distinction is the whole point.

| # | Stage | Exit criterion | Status |
|---|---|---|---|
| 0 | **Thesis & contracts** | PRD with frozen §3/§4/§5, schema v1.1, rate table with cited sources | ✅ DONE (`turnstile-prd.md`, 23 golden fixtures, contract-test gate) |
| 1 | **The instrument** | trace→pricing→verdict→10 detectors→replay→stats→dashboard, all reviewed, all fixtures-exercised | ✅ DONE — 11 packages, ~53 commits in ~48 h, external audit (Opus 4.6) + all 5 findings fixed, G1 recorder-redesign built (`opencode/g1-recorder-redesign`, pending review) |
| 2 | **The measurement** | a real paid replay matrix → Tier-1 numbers (Δcost, outcome-preservation, CI, divergence) with reproducibility manifest | 🟡 ~50% — all machinery built + guarded + checkpointed; **zero completed paid runs**; blocked on the validity fixes in `07` (CR-A/CR-B/H-1), then smoke #3 |
| 3 | **The evidence** | dashboard rendering REAL run output; METHOD/LIMITATIONS/README; Appendix-B numbers memorizable | 🟡 ~45% — dashboard renders real fixture-scale data today; corpus-scale regen pending stage 2; the three docs unwritten |
| 4 | **The demo** | the 4-minute recording per `docs/DEMO.md` with the two-tier discipline intact | 🔴 ~10% — script + sweep curves + judgment lines exist; nothing recorded |
| 5 | **GTM motion** | first CTO conversations with a defensible number | ⬜ not started (correctly — nothing to show yet) |

**Honest one-liner:** the *product's brain* is finished and audited; the *proof* is one clean paid run away; the *story* is one recording away. The remaining engineering risk is concentrated in three specific, priced findings — not in open-ended construction.

## 2. How far we've come (the concrete ledger)

**Built (all reviewed under SDD discipline — implementer + diff review + fix loop, ledger-tracked):**
- `schema` — frozen OTel/GenAI-native trace schema v1.1, 23 golden fixtures incl. effect-edge + overlap shapes, contract-test CI gate
- `pricing` — span-level cost engine, rate table (dated/cited), telephony attribution invariant
- `verdict` — Resolution Ledger: 5-source evidence precedence, unknown-caps-confidence rule, rejected-handoff ≠ ESCALATED, GAP-05 turn-of-no-return fix
- `detectors` — all 10 PRD waste classes with verbatim detection rules + harness + sweep
- `stats` — Wilson interval, deterministic bootstrap, aggregation with documented subset rules
- `dashboard` — static surface rendering real pipeline output (flame graph, fleet CPRC_loaded, findings)
- `replay` — counterfactual engine, pinned replay per PRD §8.1, injectable `DecisionBackend` seam
- `corpus` — synthetic generator honoring the three binding constraints (cited distributions, no detector-tuning, barge-in as named parameter)
- `experiments` — baselines, variant matrix (now honestly scoped to the executable lever), fail-loud guard, reproducibility manifest, trace-level checkpointing, gated OpenAI backend (timeout/retries/progress), cost estimator, D7/D8 sensitivity sweeps (monotonic curves)
- `otel` — live recorder; G1 concurrency redesign done on my branch (turns as independent-lifetime objects; overlap expressible; D8-promotion prerequisite)

**Process assets (rare at this stage, and load-bearing):** external read-only audit + verified fix batch; `docs/GATES.md` instrument-honesty gates (G1/G2); `HANDOFF.md` + the SDD ledger as a durable decision record; the two-tier Tier-1/Tier-2 claim discipline baked into `docs/DEMO.md`/`docs/CORPUS.md`.

**Spend to date: ~$0.31** (n=2 probe $0.03 + smoke #1 $0.28). Budget approved: ~$2.69 full-matrix → revised **~$0.41 routing-only** after the variant-scope correction. The $150 credit is essentially untouched.

**Three-lane execution:** Claude (judgment/review/credit), Zen (mechanical packages), GLM/OpenCode (isolated clone, `opencode/*` branches: lint hygiene, G1, this audit). The lanes have not collided once — worktree/clone isolation worked as designed.

## 3. What's left — the ordered, priced remainder

**To a defensible Tier-1 headline (the critical path, ~1–2 focused sessions):**
1. CR-A render fix + CR-B Δcost definition + H-1 framing decision (`07` §2) — small, owner-decision-gated, $0
2. H-2 `--yes` + M-1 fail-before-spend + lint merge — trivial, $0
3. Change B concurrency per `06` §3/§6 — small, $0
4. Smoke #3: n=30 routing-only, concurrent, checkpointed (~$0.04) → **real divergence rate, real RPM ceiling, real ETA**
5. The n=250 run (~$0.41) → the Tier-1 headline + manifest
6. Dashboard regen from the real run; `docs/METHOD.md`, `docs/LIMITATIONS.md`, `README.md`; Appendix-B numbers sheet

**To the demo (after 1–6):** record the 4-minute demo per `docs/DEMO.md` — script, slide structure, and the two judgment lines already exist. Tier-2 items presented as questions with the sensitivity-sweep curves; Tier-1 items presented as measured.

**Wave-2/3 backlog (explicitly deferred, entry-criteria'd — not "left out"):** live `agent/` build on the post-G1 recorder (fidelity upgrade, NOT a demo prerequisite — `docs/CORPUS.md`); LLM judge + 60 hand labels + Cohen's κ ≥ 0.75; `PARTIALLY_RESOLVED`/`MISROUTED` via scenario registry; replay application for the 5 reserved variant fields (the D2–D10 Tier-2→Tier-1 promotions); D3 cosine half; baselines calibration against real percentiles; `pricing.py:143` assert→raise.

**Total remaining budget to a recorded demo: <$1 and no new infrastructure.** The scarce resources are two owner decisions (§3 items 1–3 in `07`) and the rate-limit/divergence unknowns that smoke #3 retires for $0.04.

## 4. GTM gap — the honest distance

**What "GTM-grade" means here** (per the PRD's own bar): a skeptical CTO watches 4 minutes and gets (a) a cost flame graph for one call, (b) a *replay-proven* cheaper path with outcome-preservation + CI, (c) a fleet margin number with the loaded-CPRC correction, (d) two Tier-2 questions (D7/D8) backed by sensitivity curves instead of invented figures, (e) limitations stated unprompted. Items (a), (d), (e) exist today. Items (b), (c) exist as *machinery* and need one clean run to become *numbers*.

**Gap analysis by component:**

| Component | GTM bar | Today | Distance |
|---|---|---|---|
| Instrument credibility | audited, refuses to overstate | ✅ two audits, gates, honesty framing | 0 |
| Tier-1 numbers | machine-produced, reproducible | machinery ✅, numbers ❌ | 1 run + 3 fixes |
| Fleet view | CPRC_loaded vs naive on real corpus | fixture-scale only | 1 dashboard regen |
| Methodology doc | challenge-proof writeup | ledger exists, doc doesn't | 1 doc |
| Demo artifact | 4-min recording | script only | 1 recording |
| Post-demo moat | judge calibration, live agent, fleet data | Wave-2/3 backlog | deliberate, priced, later |

**The genuinely open risks** (the only places the timeline can slip): divergence rate unknown — if real-model output rarely matches the synthetic register, effective n shrinks and the CI widens; the owner has already chosen the honest framing (divergence = upper bound, verdict-preservation = primary), but the *number* is unknown until smoke #3. Rate limits unknown until the same smoke. Both are $0.04 questions. Beyond those, nothing on the critical path is open-ended.

**The 0→1 verdict:** this is a *sequenced* build at roughly stage 2.5 of 5, with the hard part (a trustworthy instrument that refuses to overstate) already banked and audited. The remaining work is neither invention nor exploration — it is execution of a priced, ordered list. The project is structurally incapable of becoming a "left-out" project as long as the ledger + HANDOFF + gates discipline survives session boundaries; this file and its two companions are that discipline applied to the endgame.
