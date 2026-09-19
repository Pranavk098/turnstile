# ISS-004: Gate remedy claims on real-usage delta

- Status: contested (human call)
- Source: c2_chunk_gate (`real_usage 0.64 vs CR-B 0.34, escalate`); c1 8.3-gate only 0.55
- Problem: CR-B on original tokens may overstate chunking savings — real prompts render
  ~4x smaller than synthetic (assumption scored 0.82).
- Jev verdict: leans real-usage companion, low confidence — direction, not decision.
- Proposal: compute the real-usage arbitrage companion; gate remedy claims on it beside CR-B.
- Accept when: companion reported next to CR-B on every remedy claim; METHOD.md updated.
