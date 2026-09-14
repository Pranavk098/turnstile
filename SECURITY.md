# SECURITY

## Reporting an issue

**Do not open a public issue for a suspected vulnerability.** Email the
project owner privately at **pranavkoduruc@gmail.com** with a description of
the issue, steps to reproduce, and the commit you tested against. You will get
an acknowledgment, a fix (or a documented reason it is not a vulnerability),
and credit unless you prefer otherwise.

## Scope notes (what runs where)

- The default path — tests, `make demo`, `make serve`, `POST /api/evaluate` —
  is fully local and **makes no outbound calls**: no model APIs, no telemetry,
  no network egress. Uploaded calls are evaluated in memory and never retained.
- The paid-measurement harness (`packages/experiments`, open-loop replay) only
  contacts a model provider when `TURNSTILE_ALLOW_PAID=1` **and**
  `OPENAI_API_KEY` are both set, and it asks before every run. Never put a key
  in the repo, in CI secrets consumed by the default jobs, or in a pasted demo
  call.
- API keys, tokens, or customer audio posted to a public demo instance should
  be treated as compromised: rotate them. Prefer the local `make serve` for
  anything sensitive.
