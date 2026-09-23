# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet — the Day-5 packaging, supply-chain CI, observability, and release
workflow are now released under [0.1.0]._

## [0.1.0] — 2026-09-20 (Day-7 launch; see LAUNCH.md)

### Added

- Day-1 live eval service: `/api/*` surface (fleet, calls, evaluate,
  experiments), per-IP rate limit, `/api/status`, gzip/cache policy,
  keep-warm; demo live (Days 1–5 summaries only — no new claims; numbers
  live in docs/METHOD.md, docs/LIMITATIONS.md, PERF.md).
- Day-2 real-data ingest: native call format + Vapi/Retell provider
  adapters with the `decision_kind` honesty boundary; 50-call realistic
  sample surfaced on the demo.
- Day-3 speed: behavior-preserving hot-path optimizations, parallel
  experiment matrix, cache-hit eval, `GET /metrics` counters; PERF.md +
  committed bench harness and baselines.
- Day-4 calibrated quality: labeling tool + calibration harness, five
  rule-based quality dimensions beside cost (model-graded dimensions ship
  as declared no-ops pending calibration), barge-in waste measured Tier-1
  on real audio.
- Day-5 harden + package: 7 installable PyPI libraries
  (schema/pricing/verdict/detectors/replay/ingest/quality), supply-chain
  CI (pip-audit, bandit, CodeQL, Dependabot), structured logging + Sentry
  (DSN-gated) + `/metrics`, TestPyPI/PyPI release workflow on tags, GHCR
  image + SBOM, load harness with limits.
- Day-7 launch assets: LAUNCH.md (approved-copy drafts + domain checklist
  + claim→source table + 48h triage rota + tag instructions),
  docs/LAUNCH-METRICS.md ($0 metrics view).
