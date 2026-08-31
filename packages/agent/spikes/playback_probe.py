"""Detector-7 kill-check (v3): prove the local TTS pipeline can report THREE
distinct quantities under a barge-in — intended / generated (billed) / played
(heard) — and that D7 = generated - played is measurable without counting
never-synthesized characters.

Why v3: playback and generation must be timed on SEPARATE clocks. Piper is a
synchronous, batch-per-chunk engine, so timing playback off wall-clock lets
generation latency poison the playback position (v2 produced played=0). Here we
generate each chunk with REAL Piper (real billing, real audio duration) but
drive the PLAYBACK timeline off those real audio durations, so the two never
contaminate each other. No audio device required — the measurement is character
accounting over a timeline, not whether speakers work.

Model: a streaming TTS keeps generation ~GEN_LEAD_S of audio ahead of playback.
The caller barges in after BARGE_IN_AFTER_PLAYBACK_S of *heard* audio. On
barge-in, generation of further chunks is cancelled (never billed).

  intended         = characters in the full utterance
  generated/BILLED = characters synthesized before cancellation (real Piper calls)
  played/HEARD     = characters whose audio elapsed before the barge-in
  D7 waste         = generated - played      (billed but unheard)
  never_generated  = intended - generated    (NOT billed — excluded)

The live agent's TTS wrapper MUST set tts.synthesize.chars_synthesized = generated.

Run (native Windows or Linux/WSL2 — see README.md):
    PIPER_MODEL=/path/to/en_US-lessac-medium.onnx \
        python packages/agent/spikes/playback_probe.py
"""
import os
import subprocess
import sys
import tempfile
import wave
from shutil import which

_TMP = tempfile.gettempdir()

CHUNKS = [
    "Here is a very long explanation of our refund policy",
    "that continues well past the point",
    "where a caller would normally interrupt",
    "to ask a question,",
    "which is exactly the waste Detector 7 measures.",
]
GEN_LEAD_S = 1.0                  # streaming TTS stays this many audio-seconds ahead of playback
BARGE_IN_AFTER_PLAYBACK_S = 2.0  # caller interrupts after this much HEARD audio


def _piper_cmd() -> list[str]:
    return ["piper"] if which("piper") else [sys.executable, "-m", "piper"]


def synth_chunk(text: str, idx: int) -> float:
    """Synthesize ONE chunk with Piper (this 'bills' its characters). Returns the
    audio duration in seconds, read from the produced WAV."""
    wav_path = os.path.join(_TMP, f"probe_{idx}.wav")
    subprocess.run(
        [*_piper_cmd(), "--model", os.environ["PIPER_MODEL"], "--output_file", wav_path],
        input=text.encode(), check=True,
    )
    with wave.open(wav_path, "rb") as w:
        return w.getnframes() / w.getframerate()


def main() -> None:
    intended = sum(len(c) for c in CHUNKS)
    meta: list[tuple[int, float]] = []   # (chars, secs) for chunks actually generated
    generated_chars = 0
    gen_frontier_s = 0.0
    playback_pos_s = 0.0
    played_chars = 0

    def generate_ahead(target_audio_s: float) -> None:
        nonlocal generated_chars, gen_frontier_s
        while gen_frontier_s < target_audio_s and len(meta) < len(CHUNKS):
            j = len(meta)
            secs = synth_chunk(CHUNKS[j], j)          # REAL Piper — bills these chars
            meta.append((len(CHUNKS[j]), secs))
            gen_frontier_s += secs
            generated_chars += len(CHUNKS[j])

    i = 0
    while i < len(CHUNKS):
        generate_ahead(playback_pos_s + GEN_LEAD_S)   # keep generation ahead of playback
        if i >= len(meta):
            break
        chars_i, secs_i = meta[i]
        if playback_pos_s + secs_i <= BARGE_IN_AFTER_PLAYBACK_S:
            played_chars += chars_i                   # whole chunk heard
            playback_pos_s += secs_i
            i += 1
        else:                                         # barge-in lands mid-chunk
            frac = max(0.0, BARGE_IN_AFTER_PLAYBACK_S - playback_pos_s) / secs_i
            played_chars += int(chars_i * frac)
            break                                     # generation of later chunks is cancelled

    never_generated = intended - generated_chars
    d7_waste = generated_chars - played_chars

    print(f"intended (full utterance)     = {intended}")
    print(f"generated / BILLED            = {generated_chars}")
    print(f"played / HEARD                = {played_chars}")
    print(f"D7 waste (billed - played)    = {d7_waste}")
    print(f"never generated (NOT billed)  = {never_generated}")

    ok = 0 < played_chars < generated_chars <= intended and d7_waste > 0
    print("KILL-CHECK:",
          "PASS - intended/generated/played are distinct and ordered; "
          "D7 = generated - played is measurable and excludes never-generated chars"
          if ok else
          "FAIL - could not measure the three quantities distinctly; re-plan audio layer")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
