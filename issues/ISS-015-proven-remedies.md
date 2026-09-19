# ISS-015: Replay-executable remedies (conditional → proven)

- Status: future
- Source: Track C future-item 4; LIMITATIONS §3 conditional bucket; guard.py BACKEND_APPLIED
- Problem: context_strategy / prefix_caching / retrieval_policy / tool_batching savings
  sit in the conditional bucket, unverified (H-1), some replay as no-op.
- Proposal: build replay-executable transforms with preservation measurement; promote
  through the §8.3 gate or keep conditional — never fold silently.
- Accept when: a remedy graduates via the gate with CIs, or its conditional label stays.
