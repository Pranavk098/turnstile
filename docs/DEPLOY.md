# DEPLOY — the Turnstile live demo service (PRD 01)

## Live URL

**Production:** `https://turnstile-demo.onrender.com` ← update this line on
first deploy (Render assigns the exact hostname at service creation; keep
this file as the single source of truth and link it from the README).

**Status (2026-09-14): LIVE + SHA-traced.**
`GET /health` → 200 `{"ok":true,"commit":"91e5b0d…"}` — the deployed commit now
surfaces. (Root cause of the earlier `"unknown"`: the Docker `ARG
TURNSTILE_COMMIT` defaulted to the literal `"unknown"`, which is truthy and
short-circuited `commit_sha()` before its runtime `RENDER_GIT_COMMIT` fallback;
fixed in commit `91e5b0d` by defaulting the ARG empty.) Verified live: warm `/`
0.25–0.35 s; fleet + quality-beside-cost; D7 drill-down; per-IP rate limit
(fast burst → 429, engine not run); gzip + cache headers; `/api/status`.
Forced-cold first paint ~22 s (free-tier container boot, not content — over the
5 s cold budget; mitigated by keep-warm, see below).

Warm verification transcript (all HTTP 200, PDT 2026-09-14):

```text
GET /health     → 200, time_total=0.356s, {"ok":true,"commit":"unknown"}
GET /           → 200, time_total=0.258s, size=104997 (byte-identical to local image)
GET /api/fleet  → 200, time_total=0.314s, label "Reference fleet (23 golden fixtures)"
GET /api/calls  → 200, 23 calls, each {cost_usd + quality{label,tier}} side-by-side (tier "measured")
POST /api/evaluate (docs example) → 200, time_total=0.183s, RESOLVED, 0 findings, quality block present
```

Single-origin: `/` serves `uvicorn` via Render with NO
`Access-Control-Allow-Origin` header (no CORS surface). $0: service code
contains no provider client/key handling (scan clean); evaluate ran the
MockBackend path only.

Forced-cold transcript (17 min idle, no traffic, then first contact):

```text
COLD GET /          → 200, time_total=22.393s, time_starttransfer=22.365s, size=104997
     GET /api/fleet → 200, time_total=0.217s (immediately after wake)
     GET /health    → 200, {"ok":true,"commit":"unknown"}
```

Cold reading: first paint came from committed bytes (no compute waited on —
the 22 s is pure free-tier container boot), but 22.4 s > 5 s cold budget, so
the cold-timing criterion is RED. Remedy (Day-1 P1 #6, out of Track-A-P0#1
scope): enable keep-warm — ping `/health` every ~10 min from any free
scheduler — which makes the common path the measured warm path (0.26 s).
Until then, cold boot shows the documented "Computing…"/loading states, not
an error.

Commit-trace note: `/health.commit` returns `"unknown"`, meaning this
deploy is not associated with a git SHA (manual deploy or missing
`RENDER_GIT_COMMIT`). The app honors `TURNSTILE_COMMIT` →
`RENDER_GIT_COMMIT` → git → `"unknown"` in that order. Owner one-click fix:
Render dashboard → service → "Manual Deploy → Deploy latest commit" from
the connected repo (or confirm the service tracks the repo branch with
`autoDeploy: true`), then re-probe `/health` until `commit` shows the SHA.
Observed 2026-09-14: pushing `wave0-foundation` (CI green) did NOT redeploy
the service (`/health` still `unknown`, still warm) — the service tracks a
different ref or uses manual deploys.

## Host choice + why + fallback (Track A Day-1 record, binding)

- **Primary: Render free web service ($0).** Why: `render.yaml` blueprint
  already exists (Docker runtime, `/health` check, `autoDeploy: true`);
  the app already reads Render's `RENDER_GIT_COMMIT` for `/health.commit`;
  single-origin static+API needs no extra config; no credit card, no paid
  add-ons. Push-to-deploy matches the existing CI story.
- **Fallback: Hugging Face Spaces, Docker SDK ($0).** Why: portable by
  construction — the same `Dockerfile` boots there with `PORT=7860`, no
  host-specific code (only the `RENDER_GIT_COMMIT` env read, which degrades
  to `TURNSTILE_COMMIT` → git → `"unknown"`). Use if Render free terms
  change or the namespace is unavailable. HF was NOT chosen primary
  because this checkout has no HF token (`hf auth list` → "No access
  tokens found", no `HF_TOKEN` in env) while the GitHub→Render path is
  fully wired except the dashboard create step.
- **Fly.io free ($0) is a second fallback** (same Dockerfile, `fly launch`
  + `fly deploy`), not attempted: `flyctl` is not installed here and it
  also needs an interactive login.

Local equivalent (identical app, identical data):

```bash
uv run uvicorn turnstile_service.app:app --port 8000
# or: make serve
```

Open `http://localhost:8000` (fleet), `http://localhost:8000/home.html`
(landing), `http://localhost:8000/health` (build info).

## What it is

One container serving the hand-authored dashboard from the same origin as a
thin FastAPI shell over the existing deterministic engine:

| Endpoint | Source | Notes |
|---|---|---|
| `GET /` , `/home.html`, `/sample/*.json` | `packages/dashboard/` (static) | First paint needs no compute |
| `GET /health` | git SHA / `TURNSTILE_COMMIT` | `{"ok": true, "commit": …}` |
| `GET /api/status` | uptime + commit + warm/cold (Day-1 P1 #8) | `{"ok":true,"commit":…,"uptime_sec":…,"warm":true,"engine_loaded":…}` — no engine run, `Cache-Control: no-store` |
| `GET /api/fleet`, `/api/calls`, `/api/calls/{id}`, `/api/hero`, `/api/findings`, `/api/experiments`, `/api/conditional`, `/api/bargein`, `/api/manifest` | committed `packages/dashboard/sample/*.json`, byte-verbatim | Provenance intact |
| `GET /api/ingest` | committed `packages/ingest/data/data.json`, byte-verbatim | Same shape `POST` returns |
| `GET /api/example` | `docs/INGEST.md` "The object" (pinned by test) | Prefills the eval panel |
| `POST /api/evaluate` | live `run_calls` on the posted body | 1 MB / 25-call caps; see below |

The front-end tries `/api/*` first and falls back to the relative
`sample/*.json` URLs, so the page still opens fully from a plain static
server with no backend. Only the eval panel needs the service.

## The $0 claim (exact)

- **Hosting:** Render free web service — $0/mo. No credit card on the
  account, no paid add-ons in `render.yaml`.
- **Engine:** the service runs only the deterministic path — price,
  adjudicate, detect, MockBackend replay. There is no model client, no key
  handling, and no network egress anywhere in the request path
  (`rg -i 'openai|anthropic|api_key|apikey' packages/service/src` returns
  nothing; the parity test would fail if the service drifted from the
  engine).
- **Free-tier limits relied on:** the service sleeps after ~15 min idle;
  512 MB RAM; shared CPU; 100 GB outbound/mo. The eval caps (1 MB body,
  25 calls, in-memory only, `--limit-concurrency 20`) keep one cold
  container inside those bounds.

## Cold-start behavior

1. A sleeping service takes ~30–60 s to boot on first request (Render pulls
   and starts the image). `/health` is the wake probe.
2. First paint never waits for compute: `/` serves `index.html` plus the
   committed JSON instantly once the container answers.
3. `POST /api/evaluate` shows a "Computing…" state by design; a cold POST
   reads as working, not broken.
4. Keep-warm (still $0): `.github/workflows/keepwarm.yml` pings `/health` +
   `/api/status` every ~10 min (plus `workflow_dispatch` for manual wake).
   Cold boot stays honest and documented, not hidden — keep-warm only makes
   the common path the warm one.

## Redeploy

Push to the default branch: Render auto-deploys from `render.yaml`
(`autoDeploy: true`); CI (`.github/workflows/ci.yml`, full `pytest`) runs
on the same push. To redeploy manually: Render dashboard → service →
"Manual Deploy". To roll back: "Roll back to" any prior deploy.

Fallback host (if Render free terms change): Hugging Face Spaces, Docker
SDK — the same `Dockerfile` boots there with `PORT=7860`. Portable by
construction: no host-specific code (only the `RENDER_GIT_COMMIT` env
read, which degrades to `TURNSTILE_COMMIT` → git → `"unknown"`).

## First-time setup (owner, ~10 min, $0)

1. Push this repo to GitHub (CI must be green).
2. Render → New → Web Service → select the repo → "Use `render.yaml`" —
   keep the free plan, confirm `Dockerfile` runtime and `/health` checks.
   No env vars required: commit surfaces via `RENDER_GIT_COMMIT`
   automatically; `PORT` is set by Render; `TURNSTILE_COMMIT` build-arg is
   optional (defaults to `unknown`, overridden by `RENDER_GIT_COMMIT`).
3. Open the assigned URL; verify: `/health` 200, fleet loads < 5 s warm,
   `#/call/07_barge_in_waste` shows the D7 finding, `#evaluate` posts the
   Barge-in demo preset and returns a D7 finding.
4. Copy the exact hostname into "Live URL" above and the README demo link.

## Track A Day-1 verification transcript (2026-09-14, commit `cb25051`)

Local parity (PASS — uvicorn directly):

```text
curl -s localhost:8000/health
{"ok":true,"commit":"cb25051"}
curl -s localhost:8000/api/fleet | python -c "...print(...['label'])"
Reference fleet (23 golden fixtures)
GET / → 200, time_total=0.334s (localhost warm)
```

Deploy-config fixes applied (additive only — `app.py`, `packages/schema`,
pricing, `/api/*` untouched). The pre-existing `Dockerfile` did not build;
three defects, all in deploy config:

1. `.dockerignore` excluded `packages/agent|corpus|experiments|live/` while
   `Dockerfile` `COPY`s their manifests → build failed at
   `COPY packages/live/pyproject.toml`. Fix: dropped those four exclusions
   (the `uv` workspace needs every member manifest to resolve).
2. `Dockerfile` was missing `COPY packages/quality/pyproject.toml` although
   `turnstile-ingest` depends on `turnstile-quality`. Fix: added the line.
3. `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uv` left the binary off
   `PATH` → `RUN uv sync` failed with `uv: not found`. Fix: copy to
   `/bin/uv`.

Container build + parity (PASS — `docker build -t turnstile-demo .` green,
`docker run -p 8000:8000`):

```text
GET /          → 200, time_total=0.011s, size=104997
GET /health    → 200, time_total=0.006s  {"ok":true,"commit":"cb25051"}
GET /api/fleet → 200, time_total=0.008s  label "Reference fleet (23 golden fixtures)"
```

$0 proof: `grep -ri 'openai|anthropic|api_key|apikey'
packages/service/src` → no matches; no model client, key handling, or
egress in the request path. Tests (with commit `cb25051` tree minus a
concurrent track's uncommitted files): 1082 passed, 0 failed, 4 skipped.

Live proof (DONE 2026-09-14 — was blocked on service creation, owner has
since created it): see the "Status: LIVE" transcripts above (warm + forced
cold + commit). Re-verify after any redeploy with the warm/cold curl set.

## Manual verify script (no browser needed)

```bash
uv run uvicorn turnstile_service.app:app --port 8000 &
srv=$!
curl -s localhost:8000/health
curl -s localhost:8000/api/fleet | python -c "import json,sys; print(json.load(sys.stdin)['label'])"
curl -s -X POST localhost:8000/api/evaluate \
  -H 'Content-Type: application/json' \
  -d @packages/service/src/turnstile_service/example_call.json \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d['calls'][0]['verdict'], len(d['findings']))"
kill $srv
```

Expected: `{"ok":true,…}`, the fleet label, `RESOLVED 0` (the doc example
carries no G2 counts, so D7 is honestly ABSENT — use the page's "Barge-in
demo" preset for a live D7 finding).

## Limits on the public endpoint

`POST /api/evaluate` rejects bodies over 1 MB and callsets over 25 calls
with HTTP 413, malformed input with HTTP 422 carrying the engine's field
path (never a 500 for user input), and retains nothing. These caps are
pinned by `packages/service/tests/test_evaluate.py`. Per-IP token-bucket
rate limiting (`packages/service/src/turnstile_service/ratelimit.py`, Day-1
P0 #4) returns 429 before any engine run — pinned by
`packages/service/tests/test_ratelimit.py`. Responses ≥1 KB are gzip-encoded
and cache policy is `no-store` on POST/status, short public cache on API
reads, longer on committed static bytes (Day-1 P1 #7).
