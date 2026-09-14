# DEPLOY — the Turnstile live demo service (PRD 01)

## Live URL

**Production:** `https://turnstile-demo.onrender.com` ← update this line on
first deploy (Render assigns the exact hostname at service creation; keep
this file as the single source of truth and link it from the README).

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
4. Optional keep-warm (still $0): ping `/health` every ~10 min from any free
   scheduler (e.g. GitHub Actions `schedule` + curl). Not configured by
   default — cold boot is honest and documented, not hidden.

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
3. Open the assigned URL; verify: `/health` 200, fleet loads < 5 s warm,
   `#/call/07_barge_in_waste` shows the D7 finding, `#evaluate` posts the
   Barge-in demo preset and returns a D7 finding.
4. Copy the exact hostname into "Live URL" above and the README demo link.

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
pinned by `packages/service/tests/test_evaluate.py`.
