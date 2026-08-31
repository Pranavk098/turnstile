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

## Setup — native Windows is the easy path (no WSL/Docker needed)

This probe is plain Python + a TTS + an audio device. It runs fine on **native
Windows**, where audio hardware works without the WSLg setup. (WSL2 is only
needed later for the Pipecat `agent/`, not for this probe. Do NOT run it inside
Docker Desktop's `docker-desktop` WSL VM — that's a minimal utility VM with no
Python.)

Only `piper-tts` is needed — **no audio device / sounddevice**. The probe drives
the playback timeline off the real audio *durations* Piper produces, so it
measures the character accounting without touching speakers (v3).

**Windows PowerShell** (run from a writable dir, never `C:\Windows\System32`):
```powershell
py -m venv $env:USERPROFILE\.turnstile-probe
& $env:USERPROFILE\.turnstile-probe\Scripts\Activate.ps1
pip install piper-tts
cd $env:USERPROFILE
python -m piper.download_voices en_US-lessac-medium
$env:PIPER_MODEL = "$env:USERPROFILE\en_US-lessac-medium.onnx"
cd "$env:USERPROFILE\OneDrive\Desktop\Turnstile"
python packages\agent\spikes\playback_probe.py
```

**Linux / WSL2 Ubuntu (alternative):**
```bash
python3 -m venv ~/.turnstile-probe && source ~/.turnstile-probe/bin/activate
pip install piper-tts
PIPER_MODEL=/path/to/en_US-lessac-medium.onnx python packages/agent/spikes/playback_probe.py
```

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

- Command: `python packages\agent\spikes\playback_probe.py` (native Windows, Piper en_US-lessac-medium), 2026-08-30
- intended / generated (billed) / played (heard): **190 / 52 / 33**
- D7 waste = generated − played: **19**  (never_generated = 138, correctly excluded)
- Verdict: **KILL-CHECK PASS** — the pipeline reports the three quantities distinctly; Detector 7 is buildable on Path B.
