# Audio playback kill-check (Detector 7 gate)

This spike answers the one critical Wave-0/1 risk: **can the local TTS/audio
pipeline report, under a barge-in, the three quantities Detector 7 needs — not
two?** If not, Detector 7 (barge-in waste — the demo moment) is either
unbuildable or overstated, and the audio layer must be re-planned before the
live `agent/` build (spec §11 DoD #5, §12).

## The three numbers (why two isn't enough)

A probe that only reports "played 61 of 184 characters" cannot tell you which
of these happened to the 123 unheard characters:

- **synthesized (generated) then discarded unheard** → they were **billed** → real D7 waste.
- **never synthesized** (generation cancelled on barge-in) → **never billed** → counting them **inflates** D7 in exactly the direction a skeptic attacks.

So the probe models a streaming TTS that generates *ahead* of playback by a
buffer, stops both on barge-in, and reports:

| quantity | meaning |
|---|---|
| `intended` | characters in the full utterance |
| `generated` / **BILLED** | characters actually synthesized before cancellation |
| `played` / **HEARD** | characters the caller actually heard |

`D7 waste = generated − played` (billed but unheard). `never_generated =
intended − generated` is **excluded**. The schema follows this: the live
agent's TTS wrapper MUST set `tts.synthesize.chars_synthesized = generated`
(billed), never `intended`.

## Setup (WSL2 / Ubuntu)

```bash
python3 -m venv ~/.turnstile-probe && source ~/.turnstile-probe/bin/activate
pip install piper-tts sounddevice numpy
# Download a Piper voice, e.g. en_US-lessac-medium, per https://github.com/rhasspy/piper
```
Piper needs an audio output device; WSLg on Windows 11 provides one by default.

## Run

```bash
PIPER_MODEL=/path/to/en_US-lessac-medium.onnx \
    python packages/agent/spikes/playback_probe.py
```

## Interpreting the result

- **`KILL-CHECK: PASS`** — the three numbers come back distinct and ordered
  (`played < generated ≤ intended`) with measurable `D7 = generated − played`.
  Detector 7 is buildable on Path B; record the numbers below and note that the
  live TTS wrapper must expose `generated`.
- **`KILL-CHECK: FAIL`** — the pipeline can't separate billed-unheard from
  never-generated. **STOP** and pick a fallback before building on it:
  1. count audio frames written to the sink before cancellation (→ generated),
  2. derive generated from generation-time × engine char-rate (state error bar),
  3. switch framework — cheap now, catastrophic at hour twenty.

## Result log

_(fill in after running)_

- Command:
- intended / generated (billed) / played (heard):
- D7 waste = generated − played:
- Verdict:
