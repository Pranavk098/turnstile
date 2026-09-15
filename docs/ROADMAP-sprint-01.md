# Sprint 01 — one week to "tangible & published" (7 × 12h days)

**As of `cb25051` (CI green, 1079 tests, 13 packages, Apache-2.0).** The *instrument*
is built and rigorous; what's missing is everything that turns a strong repo into a
*thing people can find, run, trust, and cite*. This sprint closes that gap.

## Where we stand (honest)

- **Strong:** schema→pricing→verdict→detectors(×10)→replay→experiments→ingest(+Vapi)
  →live(voice)→service(API+cache+async jobs)→quality(calibration-gated)→dashboard.
  1079 tests, CI green, honesty discipline intact, two-audience README + OSS hygiene.
- **Missing (the "bare minimum OSS" gap):**
  1. **Invisible** — no live URL (Render/DEPLOY assets exist, not deployed).
  2. **All synthetic** — no real provider data has flowed publicly.
  3. **"Fast" is unmeasured** — caching/async exist, but no benchmarks or profiling.
  4. **Quality is pending** — judge dims are calibration-gated no-ops; not yet real.
  5. **Not installable / not discoverable** — no PyPI, no docs site, no launch.

## The five pillars (what the week buys)

Visible → Real → Fast → Trustworthy-at-scale → Discoverable. Ordered so the live URL
and real data exist *before* launch day.

## Deferred items — status now

| Deferred item | Now? | Where |
|---|---|---|
| Rate limiting, keep-warm (01) | **Apply now** — a public URL makes both justified | Day 1 |
| Cache/job observability (03) | **Apply now** — needed for the perf story | Day 3 |
| Retell adapter (02) | **Apply now** — provider breadth for launch | Day 2 |
| Judge calibration + barge-in-measured (04) | **Apply now** — biggest quality unlock | Day 4 |
| Weekly link-health job (06) | **Apply now** — trivial | Day 5 |
| D9 tier-2 forwarded-call rule (02) | Only if real forwarded-call exports appear | Day 2 (if data) |
| Real *paid* variant sweep (03) | Stay deferred — not $0 | — |
| React/Solid rewrite (05) | Stay deferred — vanilla + docs site suffice | post-sprint stretch |

## $0 / budget

Everything stays free-tier **except** two places where a *small* spend buys
disproportionate value, flagged inline: **Day 4** (a reference-labeler model for the
calibration set) and **any real-data acquisition** (Day 2). Nothing else costs money.

## Delegation

OpenCode implements the bulk each day; **Claude reviews + owns the judgment calls**
(host choice, calibration methodology, security triage, launch copy). Realistic pace
is gated by review cadence, not typing — treat each day's list as a full 12h of
implement-then-review, not a checklist to rush.

---

## Day 1 — Go live + harden the public edge
**Why:** a clickable URL is the single biggest status change; a public endpoint needs
the deferred rate-limit + keep-warm *now*.
- Deploy the FastAPI service to a **free** host. Recommend **Hugging Face Spaces
  (Docker)** — you're already authenticated on HF, it's free, discoverable, and is
  itself a publishing domain — or Render/Fly free. (Dockerfile + render.yaml already exist.)
- Wire the deferred **per-IP rate limiting** (in-memory token bucket, before any engine
  run) and **keep-warm** (free scheduler pinging `/health`, or HF Spaces' own warmth).
- Verify the live demo shows **quality beside cost** on first screen; fill the live URL
  into `docs/DEPLOY.md`; flip the README badge from "coming soon" to the URL.
- **Done:** cold open → fleet + quality < 5s; paste-a-call works; 429 past the limit;
  README badge links to a working page.

## Day 2 — Real-provider data + breadth
**Why:** kills the "all synthetic" objection; "run on your own calls" made literally true.
- Get **one real export** through ingest (a real Vapi/Retell call if you have an account;
  else map a public task-oriented dialogue dataset, labeled honestly as such). *(small
  spend / account only)*
- Build the **Retell adapter** (deferred) reusing `provider_info` → "supports Vapi + Retell."
- If real forwarded-call data appears, build the **D9 tier-2 forwarded-call rule**; else
  keep it deferred.
- Surface real-data provenance on the live demo.
- **Done:** `--provider retell` runs; live demo has a labeled "real-shaped data" section.

## Day 3 — Make the logic faster (measured)
**Why:** turn "feels fast" into benchmarked speedups.
- Build a **benchmark harness** (pytest-benchmark or timed script) over
  price→verdict→detect→replay on N traces; record a baseline.
- **Profile** hot paths (cProfile/py-spy): pricing loop, detectors, replay aggregation;
  optimize the top 2–3 (numpy vectorization, precompute, cut redundant pydantic revalidation).
- **Parallelize the experiment matrix** (pool over independent traces) in the experiments
  layer + the service job runner.
- Add the deferred **cache/job observability** (hit-rate, timings) and publish a **PERF.md**
  with before/after and methodology.
- **Done:** matrix benchmark shows a real speedup; hit-rate visible; PERF.md committed.

## Day 4 — Quality: "pending" → "calibrated"
**Why:** the deferred judge implementations + barge-in-measured are the biggest
quality-credibility unlocks.
- Build a **calibration harness + a tiny labeling tool** (CLI/HTML to hand-label calls).
- Assemble a **~60-conversation labeled set** (strong reference model pre-labels + human
  spot-check). *(small model spend — keep minimal)*
- Compute **Cohen's κ + ECE**; if κ ≥ 0.75, ship faithfulness/relevance judges (paid-gated,
  off by default); else commit the **honest calibration report** and keep them pending.
- Wire **barge-in courtesy → measured** using the live agent's real Piper playback spans.
- **Done:** κ/ECE report committed; judges score only if the gate passes; barge-in courtesy
  reads `measured` on real-audio calls.

## Day 5 — Production hardening + packaging + release
**Why:** the "robust level" — security, observability, installability, a versioned release.
- **PyPI packaging**: publish the core library packages so `pip install turnstile-*` works.
- **Supply-chain**: pip-audit + bandit + GitHub **CodeQL** + **Dependabot** in CI; fix findings.
- **Observability**: structured logging + **Sentry (free)** on the service; a `/metrics` endpoint.
- **Load test** the live service (k6/locust free); document limits.
- Fix the **Node 20 CI deprecation** (bump actions); add the optional weekly link-health job.
- Tag **v0.1.0** + `CHANGELOG.md`.
- **Done:** `pip install` works in a clean venv; CodeQL/pip-audit green; v0.1.0 tagged.

## Day 6 — Docs site + narrative assets
**Why:** professional docs + shareable assets = credibility and discoverability.
- **Docs site** (mkdocs-material → GitHub Pages): methodology, honesty framing, ingest
  guide, quality-eval guide, auto API reference, the PERF story.
- **README polish**: a hero GIF/screenshots of the live demo (quality beside cost),
  quickstart, full badge row (PyPI, docs, CI, license, demo).
- Record a **2–4 min demo video** (reuse the PRD's demo script, now with quality beside cost).
- **Done:** docs site live; README renders with GIF + working links; video recorded.

## Day 7 — Launch across domains
**Why:** "publish on various domains" — make it tangible and known.
- Launch writeups: a **blog post** (methodology + honesty thesis + the barge-in number),
  **Show HN**, **Product Hunt**, r/MachineLearning + r/LocalLLaMA, a LinkedIn/X thread,
  the **Hugging Face Space**, and submissions to relevant **awesome-lists** (awesome-llm-eval,
  awesome-voice-ai).
- Final QA: every link, the live demo, CI green, PyPI, docs.
- Contributor on-ramp: issue templates triage + a "good first issue" set + CONTRIBUTING CTA.
- **Done:** live on ≥3 domains + a v0.1.0 announcement; everything green.

---

## End-of-week definition of "tangible & published"
A clickable live demo showing quality beside cost on real-shaped data; `pip install`
that works; a docs site; measured performance numbers; a versioned, security-scanned
v0.1.0; and a launch on ≥3 public domains — all $0 except the two flagged small spends.

## Post-sprint stretch (not this week)
React console rewrite; more provider adapters; the paid open-loop preservation study
on real traffic; a hosted multi-tenant version.
