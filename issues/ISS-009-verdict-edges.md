# ISS-009: Verdict binding edge-case review

- Status: contested (human call)
- Source: verdict_audit (`unresolved 0.61, conf 0.48, escalate`; 0.29 FALSE_RESOLVE mass)
- Problem: free-substring match + 4-char intent-token filter are UNVERIFIED on paraphrase
  and opaque IDs (`adjudicate.py:198-226`); low-confidence backing means don't over-read.
- Jev verdict: leans current, with meaningful dissent — review the edges, keep the rule.
- Proposal: add paraphrase/opaque-ID fixtures; tighten or document binding limits.
- Accept when: new fixtures pinned; B3 limits written in code comment + docs.
