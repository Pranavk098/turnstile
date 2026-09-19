# ISS-006: Fail-closed paid gate at submit time

- Status: proposed
- Source: service_audit (`submit_gate 0.71, review` vs worker-refuse 0.23)
- Problem: paid guard fires at worker-run (202 accepted, then `error`) — too late
  (`jobs.py:263-267`). Env-injected key on Render is UNVERIFIED against.
- Jev verdict: reject at submit (422/500, never 202).
- Proposal: move the MockBackend-only check to submit + audit trail.
- Accept when: `TURNSTILE_ALLOW_PAID=1` + paid backend → submit rejected; test pins it.
