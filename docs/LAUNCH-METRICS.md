# LAUNCH-METRICS.md — lightweight launch metrics (P1, all $0)

> Manual or free-API only. No paid analytics, no tracking pixels, no telemetry
> added to the product. Record snapshots in the log below; owner updates.

## Collection (all $0)

| Signal | How (free) | Cadence |
|---|---|---|
| GitHub stars / forks / traffic (views, clones, referrers) | Repo → Insights → Traffic (owner-only views); stars/forks are public; `https://img.shields.io/github/stars/Pranavk098/turnstile` badge for README-side display | stars: weekly; traffic: 48h + weekly (traffic data expires after 14 days — snapshot it) |
| PyPI downloads | `https://pypistats.org/packages/turnstile-<pkg>` per library (7 libs: schema, pricing, verdict, detectors, replay, ingest, quality); shields: `https://img.shields.io/pypi/dm/turnstile-schema` | weekly after first publish |
| Post performance | Native view/upvote/comment counts on HN, Reddit, Product Hunt, LinkedIn/X (screenshot + link) | 48h, then weekly |
| Demo health | Track D QA gate + Render dashboard (free tier); record any 5xx / cold-start degradation during launch traffic | 48h rota (`LAUNCH.md` §11) |

No metrics exist yet — first snapshot goes below after the owner posts.

## Log

| Date (UTC) | Stars | Forks | 14d views / clones | PyPI dl (schema) | Top referrer | Notes |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | pre-launch; nothing posted (agent posts nothing) |
