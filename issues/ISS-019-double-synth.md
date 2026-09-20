# ISS-019: Remove PiperTts double synthesis

- Status: proposed (matrix: needs-evidence 0.68/0.73; fix unknown — investigate first)
- Source: matrix_audit `doublesynth_*`; voice.py:315-317
- Problem: accounting pass + wav pass synthesize twice; wall-time and cost can diverge,
  and audio may not match what was measured.
- Proposal: single synthesis feeding both accounting and audio, or proof they cannot diverge.
- Accept when: one synthesis path, or divergence bounded by test.
