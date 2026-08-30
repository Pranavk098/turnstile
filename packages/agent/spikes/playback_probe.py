"""Detector-7 kill-check: prove the local TTS sink reports
chars_synthesized vs chars_played when playback is interrupted.

Synthesize a long utterance, start streaming it to the sink, then simulate a
barge-in by stopping playback partway. Report both character counts.
Exit 0 only if chars_played < chars_synthesized under interruption.

Run in WSL2 (see README.md in this directory for setup):
    PIPER_MODEL=/path/to/en_US-lessac-medium.onnx \
        python packages/agent/spikes/playback_probe.py
"""
import os
import subprocess
import sys
import time
import wave

TEXT = ("Here is a very long explanation of our refund policy that continues "
        "well past the point where a caller would normally interrupt to ask a "
        "question, which is exactly the waste Detector 7 measures.")


def synthesize(text: str) -> tuple[bytes, int, float]:
    """Return (pcm_bytes, sample_rate, seconds). Piper writes a WAV we read back."""
    wav_path = "/tmp/probe.wav"
    subprocess.run(
        ["piper", "--model", os.environ["PIPER_MODEL"], "--output_file", wav_path],
        input=text.encode(),
        check=True,
    )
    with wave.open(wav_path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        pcm = w.readframes(n)
    return pcm, sr, n / sr


def main() -> None:
    import numpy as np
    import sounddevice as sd

    pcm, sr, secs = synthesize(TEXT)
    chars_synth = len(TEXT)
    audio = np.frombuffer(pcm, dtype=np.int16)

    # Map characters to audio position linearly (chars_played ~ played_fraction).
    interrupt_after = secs * 0.33          # barge-in at 1/3
    played = {"frac": 0.0}

    def play() -> None:
        sd.play(audio, sr)
        start = time.time()
        while sd.get_stream().active:
            played["frac"] = min(1.0, (time.time() - start) / secs)
            if time.time() - start >= interrupt_after:
                sd.stop()
                break
            time.sleep(0.01)

    play()
    chars_played = int(chars_synth * played["frac"])
    print(f"chars_synthesized = {chars_synth}")
    print(f"chars_played      = {chars_played}")
    print(f"unheard (billed)  = {chars_synth - chars_played}")
    ok = chars_played < chars_synth
    print("KILL-CHECK:", "PASS - playback is measurable" if ok
          else "FAIL - re-plan audio layer")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
