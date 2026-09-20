# ISS-006: Fail-closed paid gate at submit time

- Status: implemented 2026-09-20 (app.py submit → 422 on non-MockBackend; worker guard kept)
- Test: `test_job_refuses_non_mock_backend` asserts 422 + untouched global; service suite green.
- Jev re-vote: submit_gate 0.68 vs worker_refuse 0.27 — implementation matches the vote.
- Problem: paid guard fires at worker-run (202 accepted, then `error`) — too late
  (`jobs.py:263-267`). Env-injected key on Render is UNVERIFIED against.
- Jev verdict: reject at submit (422/500, never 202).
- Proposal: move the MockBackend-only check to submit + audit trail.
- Accept when: `TURNSTILE_ALLOW_PAID=1` + paid backend → submit rejected; test pins it.
