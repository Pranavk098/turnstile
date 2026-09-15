# Day 7 PRD — Launch across domains

**Inherits `00-charter.md` in full.** Executor: OpenCode (+ owner for accounts) · Reviewer:
Claude · Depends on: **every prior day green + live** · Feeds: the world.

## Objective
Publish the project on **≥ 3 public domains** from a **verified, reliable live end-state** —
turning a strong repo into a tangible, cite-able, launched thing.

## Connection (charter §5)
This day *depends on the whole system being green*. Its first act is a **pre-launch QA
gate** that re-verifies every prior day's DoD against the **live production surfaces** —
if anything is red, the launch aborts and the defect is fixed first.

## Day-specific strict rules (add to charter §1)
- MUST NOT launch with **any** red gate: live URL down/slow, CI red, a broken link, PyPI
  install failing, docs down. The QA gate is a hard pre-condition.
- Launch copy claims MUST match the docs/`PERF.md`/calibration report exactly — **no
  overclaim**, no fabricated metrics, no impersonation.
- Anything posted to an external domain is outward-facing: it MUST be reviewed/approved by
  the owner before posting (accounts, wording, timing).

## Priority factors
### P0 — base case (MUST)
1. **Pre-launch QA gate** — a script that checks, against the **live** surfaces: demo up +
   within Day-1 budgets, CI green on tip, `pip install` works, docs site up + links
   resolve, quality-beside-cost visible. ALL green or ABORT.
2. **Launch assets** drafted + owner-approved: a blog post (methodology + honesty thesis +
   the barge-in number), a **Show HN**, a **Product Hunt** entry, ≥ 1 subreddit
   (r/MachineLearning / r/LocalLLaMA), a LinkedIn/X thread, the **Hugging Face Space**,
   and ≥ 1 **awesome-list** PR (awesome-llm-eval / awesome-voice-ai).
3. **v0.1.0 announced**; a contributor on-ramp (good-first-issues + templates live).

### P1 — build-on-top (SHOULD)
4. A lightweight launch-metrics view (stars/traffic/PyPI downloads).
5. A feedback/issue triage rota for the first 48 h.

### P2 — stretch (MAY)
6. Targeted outreach (newsletters, specific communities).

## Latency budget (charter §2)
- The pre-launch QA gate is a hard checklist; the **live demo MUST meet the Day-1
  budgets under real launch traffic** (cold < 5 s, evaluate warm p95 < 300 ms).

## Interfaces
A `scripts/prelaunch_qa.py` that dynamically probes all live surfaces and exits non-zero
on any failure; a `LAUNCH.md` with the approved copy + the domain checklist; the
awesome-list PR(s); the release notes.

## Acceptance criteria (EARS)
- WHEN the pre-launch QA runs, every gate SHALL be green **or** the launch SHALL abort with
  the failing gate named. *(check: run it; seed one failure and confirm abort)*
- WHEN a visitor arrives from a launch link, the live demo SHALL meet the Day-1 latency
  budget. *(check: timed fetch from a cold state)*
- IF the live demo returns any 5xx during the QA probe, THEN the launch SHALL abort and the
  defect SHALL be fixed before any post goes out. *(check: the QA script's 5xx guard)*
- Every launch-copy claim SHALL have a matching source in the docs. *(check: claim→source
  cross-check)*

## Recursive loop — Day-7 dynamic checks (charter §3)
Run the pre-launch QA against the **live production** surfaces as a real user (demo, PyPI,
docs, every link). Any defect → fix → re-run the *entire* QA (not just the fixed part) →
only when it is fully green may launch proceed. External posting steps that need the
owner's accounts are **environmental**: prepare + verify everything, then hand the owner
the approved copy + checklist to post. Attach the green QA transcript as the launch record.

## Risks & mitigations
- Launching on a red surface → the hard QA gate + abort-on-red.
- Overclaiming under launch scrutiny → claim→source cross-check; lead with the honesty framing.
- Traffic spike breaks the free host → Day-1 keep-warm + rate limit + a documented fallback host.

## Out of scope
Paid ads; a hosted SaaS; anything requiring spend beyond $0.

## Reviewer gate (Claude)
QA gate green against live surfaces; copy matches sources (no overclaim); ≥3 domains
prepared + owner-approved; v0.1.0 announced; the whole system verified reliable end-to-end.
