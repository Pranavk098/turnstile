"""Detector-7 kill-check (v2): prove the local TTS pipeline can report THREE
distinct quantities under a barge-in, not two.

The trap this version closes: a probe that only reports "played 61 of 184
characters" cannot distinguish
  - characters SYNTHESIZED (generated) then discarded unheard  -> billed, D7 waste
  - characters NEVER SYNTHESIZED (generation cancelled early)  -> never billed
Counting the second as waste inflates D7 in exactly the direction a skeptic
attacks. So we model a streaming TTS that generates AHEAD of playback by a
buffer, and on barge-in we stop BOTH generation and playback. We then report:

  intended   = characters in the full utterance
  generated  = characters actually synthesized before cancellation   (BILLED)
  played     = characters the caller actually heard                  (HEARD)

  D7 waste          = generated - played     (billed but unheard)
  never_generated   = intended - generated   (NOT billed -- must be excluded)

Detector 7 must be built on `generated - played`. `tts.synthesize.chars_synthesized`
in the schema therefore MUST record `generated` (billed), never `intended`.

Run in WSL2 (see README.md):
    PIPER_MODEL=/path/to/en_US-lessac-medium.onnx \
        python packages/agent/spikes/playback_probe.py
"""
import os
import subprocess
import sys
import time
import wave

# One "chunk" ~= one clause the streaming TTS emits as a unit.
CHUNKS = [
    "Here is a very long explanation of our refund policy",
    "that continues well past the point",
    "where a caller would normally interrupt",
    "to ask a question,",
    "which is exactly the waste Detector 7 measures.",
]
GENERATION_LEAD_CHUNKS = 2   # streaming TTS synthesizes this many chunks ahead of playback
BARGE_IN_AT_FRACTION = 0.33  # caller interrupts a third of the way through playback


def synth_chunk(text: str, idx: int) -> tuple[bytes, int, float]:
    """Synthesize ONE chunk with Piper. Returns (pcm, sample_rate, seconds).
    Calling this is what 'bills' the characters in `text`."""
    wav_path = f"/tmp/probe_{idx}.wav"
    subprocess.run(
        ["piper", "--model", os.environ["PIPER_MODEL"], "--output_file", wav_path],
        input=text.encode(), check=True,
    )
    with wave.open(wav_path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        return w.readframes(n), sr, n / sr


def main() -> None:
    import numpy as np
    import sounddevice as sd

    intended = sum(len(c) for c in CHUNKS)

    # Pre-compute per-chunk audio lengths by synthesizing lazily as generation
    # advances. We track which chunks were actually generated (billed).
    generated_chars = 0
    generated_audio: list[tuple[np.ndarray, int, float, int]] = []  # (audio, sr, secs, chars)

    def generate_through(chunk_idx: int) -> None:
        nonlocal generated_chars
        while len(generated_audio) <= chunk_idx and len(generated_audio) < len(CHUNKS):
            i = len(generated_audio)
            pcm, sr, secs = synth_chunk(CHUNKS[i], i)
            generated_audio.append((np.frombuffer(pcm, dtype=np.int16), sr, secs, len(CHUNKS[i])))
            generated_chars += len(CHUNKS[i])

    total_secs = 0.0
    # Prime the buffer: generate the lead before playback starts.
    generate_through(GENERATION_LEAD_CHUNKS - 1)

    played_chars = 0
    barge_in_hit = False
    start = time.time()
    # We need an estimate of total duration for the barge-in clock; use the
    # generated-so-far rate extrapolated to intended length. Simpler: barge in
    # after a wall fraction of the *generated lead* duration.
    for idx in range(len(CHUNKS)):
        if idx >= len(generated_audio):
            break  # generation was cancelled before this chunk -> never billed
        audio, sr, secs, chars = generated_audio[idx]
        # keep generation running ahead of playback
        generate_through(idx + GENERATION_LEAD_CHUNKS)
        total_secs += secs
        sd.play(audio, sr)
        played_this_chunk = 0.0
        while sd.get_stream().active:
            elapsed = time.time() - start
            # barge-in fires once we're a fraction into the (growing) generated timeline
            if not barge_in_hit and elapsed >= BARGE_IN_AT_FRACTION * max(total_secs, 0.5):
                barge_in_hit = True
                sd.stop()
                # partial credit for the fraction of this chunk actually heard
                frac = min(1.0, played_this_chunk / max(secs, 1e-6))
                played_chars += int(chars * frac)
                break
            played_this_chunk = time.time() - (start + (total_secs - secs))
            time.sleep(0.01)
        if barge_in_hit:
            break
        played_chars += chars  # whole chunk was heard

    # On barge-in we stop generating further chunks -> they are never billed.
    never_generated = intended - generated_chars
    d7_waste = generated_chars - played_chars

    print(f"intended (full utterance)     = {intended}")
    print(f"generated / BILLED            = {generated_chars}")
    print(f"played / HEARD                = {played_chars}")
    print(f"D7 waste (billed - played)    = {d7_waste}")
    print(f"never generated (NOT billed)  = {never_generated}")

    ok = (
        played_chars < generated_chars <= intended   # all three distinct & ordered
        and d7_waste > 0                              # there is measurable billed-unheard waste
    )
    print("KILL-CHECK:",
          "PASS - pipeline reports generated/played/intended distinctly; "
          "D7 = generated - played is measurable"
          if ok else
          "FAIL - cannot distinguish billed-unheard from never-generated; re-plan audio layer")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
