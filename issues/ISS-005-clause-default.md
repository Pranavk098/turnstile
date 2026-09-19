# ISS-005: Clause default + local-only barge-in label

- Status: proposed
- Source: c2_ship_default (`clause 0.78, conf 0.71, review`); transfer assumption 0.28
- Problem: sentence default wastes ~4.1%; the 4%-to-1.2% curve was measured on local
  Piper only and does not transfer to hosted streaming (`tts.py:33-45`; DEMO:21-23).
- Jev verdict: ship clause (2.3%), twice confirmed across cycles.
- Proposal: flip default to clause; stamp the curve local-Piper-only; hosted validation open.
- Accept when: default flipped + tests; docs carry the local-only label; hosted check filed.
