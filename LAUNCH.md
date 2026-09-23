# LAUNCH.md — v0.1.0 launch record (Track E, Day-7 P0-2/P0-3 + P1)

> **Status: DRAFT — owner must approve + post from owner account.**
> Per charter: no impersonation. Nothing in this file has been posted anywhere
> by the agent. Every external post below is marked
> **DRAFT — owner must approve + post from owner account**.
> Pre-launch QA gate (`scripts/prelaunch_qa.py`) is owned by Track D:
> launch proceeds only on a green QA transcript against the live surfaces.

## 0. Claim → source table (no overclaim gate)

Every number in every draft below traces to exactly one row here.
Tier vocabulary is verbatim: **measured / instrumented / not-measured**.
No bare point estimate appears without (n, dataset, seed) or a stated CI.

| # | Claim (as worded in drafts) | Source (file:line) | Tier |
|---|---|---|---|
| C1 | Recoverable margin **0.57% [0.49, 0.66]**, $0.029 on $5.07, ~$126/yr @ 1M calls (illustration, not forecast) | `docs/METHOD.md:33-40` | measured (mock replay, n=250 seed 0) |
| C2 | Margin is per-dataset: 0.57% (250-trace corpus), ~1.3% (23 golden fixtures), ~2.7% (ingest sample) | `docs/METHOD.md:46-51` | measured |
| C3 | Fork rate **7.8%** (17/217 routing pivots), identity preservation **0.985** (197/200) on non-divergent paid pivots | `docs/METHOD.md:101-111` | measured (paid n=250/seed 8) |
| C4 | Open-loop preservation-under-divergence **16.7% registry [5.8, 39.2] / 4.5% judge [0.8, 21.8]**, n=72 — cautionary, not a fleet rate | `docs/METHOD.md:169-183` | measured, small-n |
| C5 | Barge-in waste sweep: **12.1% [8.1, 16.4]** polite → 31.7% → 41.4% impatient, pooled 28.7% (interruption-heavy regime, not a typical fleet) | `docs/METHOD.md:192-211` | measured (real Piper audio, n=200 seed 7) |
| C6 | D8 silence **$0.000671/call [0.000653, 0.000689]**, flat across barge rate; synthetic acoustics (Tier-2 in kind) | `docs/METHOD.md:213-224` | measured number, Tier-2 kind |
| C7 | Speed: per-trace p95 ~8× (1253.0→155.9 µs); matrix **4.46×** parallel speedup (n=250, workers=8, MockBackend) | `PERF.md:32-62` | measured |
| C8 | Cache-hit eval 1.4 ms (<50 ms gate); cold single-call p95 66.1 ms (<300 ms gate) | `PERF.md:64-77` | measured |
| C9 | Quality: 5 rule-based dimensions measured; faithfulness + relevance ship as `not_measured` no-ops pending κ ≥ 0.75 calibration | `docs/METHOD.md:240-260` | measured / not-measured |
| C10 | **No real customer fleet yet** — every headline is "the number on *this* data" | `docs/LIMITATIONS.md:7-16` | stated boundary |
| C11 | Suite green: **1254 passed, 4 skipped** (this run, 2026-09-20); link check green (36 md + 2 html) | pytest transcript §7 / link-check §7 | measured today |
| C12 | Live demo URL `https://turnstile-demo.onrender.com` | `pyproject.toml:9`, `README.md:5` | in-repo (re-verify live at post time) |

What we do **not** claim anywhere: divergent-decision preservation at fleet scale,
D8 on real customer audio, any saving beyond the gated `route` remedy
(`docs/LIMITATIONS.md:36-48`), uncalibrated quality scores.

## 1. Blog post — DRAFT (owner must approve + post from owner account)

**Title:** The eval nobody runs: cost. A margin profiler for voice AI.

**Body:**

Voice-AI pricing is drifting toward per-resolution and per-minute, so
cost-per-resolution *is* gross margin. Token observability stops at the model;
contact-center analytics never sees the model layer. Turnstile spans both:
`call → price → verdict → detect waste → replay cheaper → report` (C12-adjacent:
architecture per `README.md:11-15`).

The honesty thesis first, because it is the product: every figure wears one of
three labels — **measured** (we stand behind it), **instrumented** (mechanism
works, size unclaimed), **not measured** (openly stated, with the path that
would measure it). An unlabeled number is a review blocker in this repo
(`CONTRIBUTING.md:27-39`). The unflattering list lives in
`docs/LIMITATIONS.md`, headlined by C10.

The number we can prove: routing eligible `route` decisions to a cheaper model
recovers **C1**, deterministic rate arbitrage re-priced from a dated rate card
and gated on preservation + a strictly-negative bootstrap CI. Small on purpose:
only the `route` decision is replay-executable today, and it is a small slice
of call cost. It differs by population (C2) — on your traffic it is whatever
your traffic is. That is the point.

The number that started it: when a caller interrupts, the TTS engine — running
far faster than real time — has already synthesized the rest of the reply.
Measured on real Piper audio at volume, barge-in waste runs **C5**: about
one-eighth of TTS spend at a polite interruption rate, rising past 40% with an
impatient caller. The pooled figure describes the interruption-heavy regime,
not a typical fleet — say so, we do.

And the cautionary number, kept apart from the margin: when the cheaper model
genuinely decides differently, outcome preservation measures **C4** — it can
act when given real tools, but narrowly (acts concentrate in `process_refund`).
Not a fleet rate. The probe that found it is the same harness that would
re-measure it on your calls.

Speed and quality beside cost: C7, C8, C9. Green suite C11.
Try it with zero install at C12; reproduce the margin free with
`uv run python packages/experiments/run_experiments.py --n 250 --seed 0`.

## 2. Show HN — DRAFT (owner must approve + post from owner account)

**Title:** Show HN: Turnstile – a margin profiler for voice AI (every number labeled by how measured it is)

**Body:**

Turnstile prices every turn of a voice-AI call, adjudicates whether it
resolved, finds ten waste classes, and proves the routing saving — the one
replay-executable remedy today — by replaying the call on a cheaper model.

Numbers, all with (n, dataset): recoverable margin C1; barge-in TTS waste C5
(real Piper audio, n=200); cheaper-model fork rate C3 with C4 kept honestly
apart. Five quality dimensions measured beside cost (C9); the two that need a
calibrated judge ship as declared no-ops.

The framing is the feature: measured / instrumented / not-measured on every
figure, full boundaries in METHOD.md + LIMITATIONS.md (C10: no real customer
fleet yet — your traffic gives your number).

Live demo: C12 · Docs: [docs URL — OWNER-APPROVAL-REQUIRED] · Suite C11.
Ask HN: what would you need to see before pointing this at real traffic?

## 3. Product Hunt entry — DRAFT (owner must approve + post from owner account)

**Tagline:** Price every voice-AI turn; prove each saving by replay.

**Description:** Turnstile is an open-source margin profiler for voice AI.
It prices every span from a dated rate table, decides whether the call
resolved, detects ten waste classes, and counterfactually replays the routing
decision on a cheaper model to prove that one saving (route is the only
replay-executable remedy today). Headline results: C1 (deterministic,
gated); barge-in waste C5 (real audio); quality scored beside cost (C9).
Everything labeled measured / instrumented / not-measured; limits up front
(C10). Links: demo C12 · GitHub [OWNER-APPROVAL-REQUIRED] · PyPI
[OWNER-APPROVAL-REQUIRED — insert after first publish].

## 4. Subreddit post (r/LocalLLaMA) — DRAFT (owner must approve + post from owner account)

> OWNER-APPROVAL-REQUIRED: re-read the subreddit's current rules/sidebar at
> post time (self-promo, flair, and "no blogspam" rules change). This draft is
> written to comply to best effort: open-source, no monetization, full
> methodology, numbers with n/dataset, limits up front.

**Title:** [OC] I built an open-source margin profiler for voice AI — it replays your calls on cheaper models to prove savings (route saving 0.57% [0.49, 0.66], n=250 seed 0; barge-in waste 12–41% sweep, real Piper n=200 seed 7)

**Body:** Local angle: the replay engine does exact rate arbitrage on the
*original* token workload — no live model call needed for the gated number
(C1), so you can quantify routing to a smaller local model before moving
traffic. What I actually measured: C1, C2, C5 (real Piper TTS, n=200),
C3 + C4 (paid nano runs, kept apart — divergence preservation is ~1-in-6 —
16.7% registry [5.8, 39.2], n=72, cautionary, not a fleet rate — narrow to
refund). What I didn't: C10. Quality C9, speed
C7–C8. Repo + demo inside; the honesty docs (METHOD/LIMITATIONS) are the real
README. Happy to answer methodology questions; will not hype what isn't measured.

## 5. LinkedIn/X thread — DRAFT (owner must approve + post from owner account)

1. Voice-AI bills per resolution now. But nobody's eval measures cost. So I built one — and gave every number a label for how measured it is. 🧵
2. The proven number is small on purpose: routing `route` decisions to a cheaper model recovers C1 — deterministic arithmetic, gated, reproducible. (C2)
3. The waste number: interrupted TTS is synthesized, billed, never heard. On real audio: C5. Your barge-in rate sets your number.
4. The cautionary number: when the cheaper model truly decides differently, preservation is C4. Kept apart from the margin, always.
5. Quality sits beside cost (C9); the two dimensions needing a calibrated judge ship as no-ops. No decoration.
6. Limits up front (C10), suite C11, demo C12. The honesty framing is the product.

## 6. Hugging Face Space stub — DRAFT (owner must approve + post from owner account)

**Title:** Turnstile — voice-AI margin profiler (demo mirror)

**Description:** Zero-install mirror of C12. Paste a call, get price +
verdict + waste findings + quality beside cost. Numbers shown are C1–C9 on
the committed demo data (C10: bring your traffic for your number). Space
runs the same frozen pipeline (`packages/schema` + pricing formulas) as the
repo — no re-implementation. [Space URL — OWNER-APPROVAL-REQUIRED: create
under owner account, then insert.]

## 7. Awesome-list PR body — DRAFT (owner must approve + post from owner account)

**Target:** awesome-llm-eval or awesome-voice-ai [OWNER-APPROVAL-REQUIRED:
confirm target repo URL + contribution format at PR time — do not freelance].

**Title:** Add Turnstile — voice-AI margin profiler with honesty-labeled numbers

**Body:**

Turnstile prices every turn of a voice-AI call, adjudicates resolution,
detects ten waste classes, and proves the routing saving by counterfactual
replay (the one replay-executable remedy today).
Notable: every surfaced number carries a measured / instrumented /
not-measured tier; METHOD.md + LIMITATIONS.md state boundaries up front
(synthetic-corpus headlines, small-n preservation, no real fleet yet).
Measured: C1; C5 (real TTS audio, n=200); C7–C8. Apache-2.0, live demo C12,
suite C11.

Suggested section: *Evaluation — Cost*. One-line entry + demo link; no other
files touched.

## 8. Domain checklist (≥3 domains; all drafts until owner posts)

| Domain | Asset | Status | Owner approval |
|---|---|---|---|
| Blog (owner's blog / dev.to / Medium) | §1 post | DRAFT | OWNER-APPROVAL-REQUIRED |
| Hacker News | §2 Show HN | DRAFT | OWNER-APPROVAL-REQUIRED |
| Product Hunt | §3 entry | DRAFT | OWNER-APPROVAL-REQUIRED |
| Reddit r/LocalLLaMA (r/MachineLearning alt) | §4 post | DRAFT | OWNER-APPROVAL-REQUIRED + re-check sub rules |
| LinkedIn / X | §5 thread | DRAFT | OWNER-APPROVAL-REQUIRED |
| Hugging Face Spaces | §6 stub | DRAFT | OWNER-APPROVAL-REQUIRED (owner creates) |
| awesome-llm-eval / awesome-voice-ai | §7 PR body | DRAFT | OWNER-APPROVAL-REQUIRED |

Pre-post gate (owner, per post): Track D QA green on that day; link C12 live;
no placeholder left unfilled; copy re-diffed vs §0 table.

## 9. v0.1.0 release — notes draft + tag instructions (owner runs)

**Release notes (draft, no new claims — summaries only):**

- Day 1 — live eval service: `/api/*` surface, rate limits, status/metrics,
  keep-warm; demo live at C12.
- Day 2 — real-data ingest: native + Vapi/Retell adapters, 50-call realistic
  sample surfaced on the demo.
- Day 3 — speed: behavior-preserving hot-path opts, parallel matrix (C7),
  cache-hit eval (C8), `PERF.md` + committed bench harness.
- Day 4 — calibrated quality: labeling tool + calibration harness, five
  rule-based dimensions beside cost, barge-in measured Tier-1 (C5, C9).
- Day 5 — harden + package: 7 PyPI libraries, supply-chain CI
  (pip-audit/bandit/CodeQL/Dependabot), structured logging + Sentry +
  `/metrics`, release workflow (TestPyPI/PyPI on tag), GHCR image + SBOM.

**Tag instructions (owner — do NOT let the agent push tags):**

```powershell
# 1. Pre-tag checks: Track D QA green; CHANGELOG §[0.1.0] filled (done here);
#    confirm the version-bump decision with Day-5 Part H
#    (pyproject.toml still reads 0.0.0 — release.yml publishes on v* tags).
# 2. Tag + push ONLY from the owner account:
git tag -a v0.1.0 -m "v0.1.0: margin profiler — proven margin, measured barge-in, quality beside cost"
git push origin v0.1.0
# 3. Then: fill the PyPI/docs/Space URL placeholders in §§2–6 and re-verify §0.
```

No `v0.1.0` tag exists yet (verified 2026-09-20: `git tag` empty); nothing
has been pushed by the agent.

## 10. Contributor on-ramp (verified links + good-first-issues)

Verified present and linked: `CONTRIBUTING.md` (setup, contract-first,
honesty labels), `CODE_OF_CONDUCT.md` (Covenant 2.1, owner contact),
`SECURITY.md` (private report path, no-outbound default), `.github/ISSUE_TEMPLATE/`
(`bug_report.md`, `feature_request.md`), `.github/PULL_REQUEST_TEMPLATE.md`
(honesty-label + frozen-contract checkboxes). Link check §7 green.

**Good-first-issues (proposed — maintainer must create these as GitHub
issues; source files in `issues/`):**

1. `ISS-008` (docs, small): stamp inline (n, dataset) on every headline +
   stale-number sweep (README/dashboard/DEMO mismatches listed in the file).
2. `ISS-019` (code, small): single synthesis feeding both accounting and
   audio in `PiperTts` (`voice.py:315-317`), or a test bounding the divergence.
3. `ISS-018` (code, medium): split the reused unknown-cap 0.6
   (`adjudicate.py:93,265-287,475-489`) with fixtures pinning each ambiguity.

## 11. 48h triage rota (P1)

| Window (from first post) | Owner task | Notes |
|---|---|---|
| 0–8h | Watch demo health + HN/Reddit threads; answer methodology Qs with §0 rows only | Never invent a number live — cite C1–C11 or say "not measured" |
| 8–24h | Triage inbound issues: label bug / question / overclaim-challenge; challenge → reply with source line | If QA-red surface found: pull the post links, fix, re-QA, re-post |
| 24–48h | Close the loop: thank reporters, file follow-up issues in `issues/`, record metrics in `docs/LAUNCH-METRICS.md` | Metrics are $0/manual (shields API + PyPI stats) |

Escalation: any 5xx on C12 or CI-red → launch pauses (Day-7 abort rule);
security report → `SECURITY.md` path, never a public thread.

## Appendix — dynamic-check transcripts (2026-09-20)

- `git tag` → empty (no v0.1.0 yet); `git log` tip `9c0b30f`.
- Root `python -m build` is NOT this repo's path (root `package=false`;
  setuptools fallback errors on the license classifier). Release path per
  `.github/workflows/release.yml:44-48` is `uv build --package turnstile-<pkg>`:
  all 7 built green (schema/pricing/verdict/detectors/replay/ingest/quality,
  sdist + wheel each).
- Wheel install: `turnstile-schema` + `turnstile-pricing` 0.0.0 wheels
  installed with `--target` on Python 3.13.12 and imported OK ($0).
  (Note: system `pip` points at Python 3.11.9, below `requires-python >=3.12` —
  use the project interpreter / `uv run`.)
- Link check: `uv run python scripts/check_links.py` → green (36 md + 2 html).
- Suite: `uv run python -m pytest` → **1254 passed, 4 skipped in 68.60s**.
