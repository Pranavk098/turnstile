# Day 1 PRD — Go live + harden the public edge

**Inherits `00-charter.md` in full.** Executor: OpenCode · Reviewer: Claude · Depends on:
nothing (this is the substrate) · Feeds: every other day.

## Objective
A public, reliable, **$0** live URL serving the demo — fleet + **quality beside cost** +
paste-a-call — with a hardened public edge (rate-limited, no cold-start dead time).

## Connection (charter §5)
This is the substrate. Day-2 data and Day-4 quality surface **here**; Day-3 speeds it;
Day-5 hardens it further; Day-6/7 link it. It MUST expose the `/api/*` surface (charter
§4) unchanged so later days extend it additively.

## Day-specific strict rules (add to charter §1)
- The host MUST be $0. **Recommended: Hugging Face Spaces (Docker)** — the owner is
  already authenticated, it's free, warm, and is itself a launch domain (Day-7). Render
  free / Fly free are acceptable alternates. The choice MUST be recorded in `DEPLOY.md`.
- The service MUST be single-origin (dashboard + API same origin, no CORS surface).
- The public endpoint MUST NOT run the engine before the rate-limit and size checks pass.
- Uploaded calls MUST be processed in memory and MUST NOT be persisted.

## Priority factors
### P0 — base case (MUST)
1. Containerized deploy **live at a stable public URL**; `/health` returns 200 + commit.
2. First screen = fleet with **quality beside cost**, rendered from committed data.
3. `POST /api/evaluate` works live (paste a call → report), MockBackend/$0 path only.
4. **Per-IP rate limiting** (token bucket) returning 429 **before any engine run**.
5. README demo badge flipped from "coming soon" → the live URL; `docs/DEPLOY.md` URL
   filled; the pre-existing DoD of PRD 01 re-verified against the live surface.

### P1 — build-on-top (SHOULD)
6. **Keep-warm** (a free scheduler pinging `/health`, or HF Spaces' own warmth) so the
   common path is never a cold start.
7. Response compression (gzip/br) + long cache headers on static assets.
8. A lightweight `/api/status` (uptime, commit, warm/cold) for the Day-7 QA gate.

### P2 — stretch (MAY)
9. A custom domain. 10. Minimal per-endpoint request counters (in-memory).

## Latency budget (charter §2, tightened)
- Cold first paint **< 5 s**; warm first paint **< 1.5 s**.
- `POST /api/evaluate` warm **p95 < 300 ms**; cache-hit **< 50 ms**.
- Rate-limit decision **< 5 ms**; MUST add no measurable latency to allowed requests.

## Interfaces
No new API shapes — deploy the existing `/api/*` (charter §4). Add only `/api/status`
(P1) and the rate-limit middleware. Deploy config: `Dockerfile` (exists), host manifest
(`render.yaml` exists / add a HF `Spacefile`/`README` header if HF), `docs/DEPLOY.md`.

## Acceptance criteria (EARS — each proven by a live dynamic check)
- WHEN a visitor opens the URL on a **cold** container, the site SHALL render the fleet
  with quality-beside-cost within **5 s**. *(check: timed curl + Browser MCP first paint)*
- WHILE no paid key is present in the environment, the service SHALL serve every demo
  path with **zero** paid calls. *(check: egress/log inspection + code scan)*
- WHEN a client exceeds the configured rate, the service SHALL return **429** and SHALL
  NOT invoke `run_calls`. *(check: burst script trips 429; server log shows no engine run)*
- IF the host cold-starts, THEN first paint SHALL still occur from committed JSON.
  *(check: force cold, measure)*
- WHEN `POST /api/evaluate` receives the doc example, it SHALL return a report with a
  quality block within the **300 ms** warm budget. *(check: timed curl)*
- The live README badge SHALL link to a page that returns 200. *(check: curl the badge href)*

## Recursive loop — Day-1 dynamic checks (charter §3)
Run against the **deployed URL** (not localhost): cold-open timing, warm-open timing,
evaluate round-trip + latency, a burst to trip 429 (assert no engine run in logs), a
no-paid-path scan, badge-link 200. Iterate until every EARS criterion + budget is green;
attach the transcript (curl outputs + measured ms + a screenshot/DOM read).

## Risks & mitigations
- Free-host cold start → keep-warm (P1) + committed-JSON first paint (P0).
- Host sleeps/sunsets → Dockerized + portable; DEPLOY.md records a fallback host.
- Abuse of the public endpoint → rate limit + size/count caps + no persistence + no egress.

## Out of scope
Paid live replay; auth/accounts; the React rewrite. Real data is Day-2.

## Reviewer gate (Claude)
Live URL meets all P0 EARS + budgets with attached transcripts; 429 proven pre-engine;
$0 proven; badge live; CI green; `/api/*` contract unchanged.
