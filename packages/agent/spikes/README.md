# Audio playback kill-check (Detector 7 gate)

This spike answers the one critical Wave-0 risk: **can the local TTS/audio sink
report how many characters were actually *played* vs *synthesized* when the
caller barges in?** If not, Detector 7 (barge-in waste — the demo moment) is
unbuildable and the audio layer must be re-planned before Wave 1 (spec §11
DoD #5, §12).

## Setup (WSL2 / Ubuntu)

```bash
python3 -m venv ~/.turnstile-probe && source ~/.turnstile-probe/bin/activate
pip install piper-tts sounddevice numpy
# Download a Piper voice, e.g. en_US-lessac-medium, per https://github.com/rhasspy/piper
```

Piper needs an audio output device. Under WSL2 you may need PulseAudio/WSLg
audio working (WSLg on Windows 11 provides this by default).

## Run

```bash
PIPER_MODEL=/path/to/en_US-lessac-medium.onnx \
    python packages/agent/spikes/playback_probe.py
```

## Interpreting the result

- **`KILL-CHECK: PASS`** (`chars_played < chars_synthesized`): playback is
  measurable. Detector 7 is buildable on Path B by mapping the interrupt
  (stop) time to a character position. Record the observed numbers below.
- **`KILL-CHECK: FAIL`**: **STOP.** The audio layer must be re-planned before
  any Wave-1 work depends on `audio.playback`. Escalate.

## Result log

_(fill in after running)_

- Command:
- chars_synthesized / chars_played / unheard:
- Verdict:
