# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Installable PyPI packaging for the 7 core libraries with clean-venv smoke tests
  (Day-5 Part A) (unreleased, pending H).
- Supply-chain CI: `pip-audit` + `bandit` + CodeQL + Dependabot with a
  release-blocking threshold gate (Day-5 Part B) (unreleased, pending H).
- Service observability: structured JSON request logging, Sentry (DSN-gated,
  inert when unset), and `GET /metrics` extending Day-3 counters
  (Day-5 Part C) (unreleased, pending H).
- CI Node-20 deprecation fix: `actions/checkout@v4` → `@v5`,
  `astral-sh/setup-uv@v5` → `@v6`, all pinned to commit SHAs; `release`
  workflow (TestPyPI on dispatch, PyPI on tag) with secret scan; weekly
  link-health job (Day-5 Part D) (unreleased, pending H).

## [0.1.0]

<!-- Part H fills this body from the merged Day-5 PRs on the green tip. -->
