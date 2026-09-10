# LIVE-AGENT — environment log (Phase 0 spike, 2026-09-08; retry 2026-09-10: GO)

## Go / no-go (retry 2026-09-10)

**GO for headless pipeline work.** Ubuntu 26.04 is installed and running;
`pipecat-ai 1.8.1` installs cleanly under the distro Python 3.14.4 and a
three-processor pipeline (script source → local transform → collecting sink)
runs headless in <1s with zero external services (no STT/LLM/TTS, no audio
devices, no network, no keys), exiting cleanly with output asserted. The
spike script lives OUTSIDE the repo (owner's WSL home,
`~/pipecat-spike/bot.py`) — nothing Pipecat-specific is committed; Phase 2
wires it into `packages/live/` on its own branch.

Caveats carried forward (all observed, none blocking Phase 2's shape):

- **Install path is user-space, no sudo needed** (sudo requires interactive
  auth in this Ubuntu): `curl -LsSf https://astral.sh/uv/install.sh | sh`,
  then `uv venv && uv pip install pipecat-ai` in `~/pipecat-spike`.
  The distro Python has NO pip module (`No module named pip`) — uv is the
  way in. The repo itself is visible from Ubuntu at
  `/mnt/c/Users/prana/OneDrive/Desktop/Turnstile/pyproject.toml`, but the
  spike venv lives in the Linux home dir (9p mounts are slow for venvs).
- **Machine:** 20 cores, ~15 GB RAM available to WSL — plenty for local
  Whisper + Piper in Phase 2.
- **API drift:** `PipelineTask`/`PipelineRunner` are deprecated since Pipecat
  1.3 (use `PipelineWorker`/`WorkerRunner` + `add_workers()`); the deprecated
  shims still work. Phase 2 should use the new names. A mid-pipeline
  `EndFrame` does NOT terminate the 1.8 runner — shutdown is via task cancel
  (`CancelFrame` unwinds cleanly, observed in the spike log).
- **Audio:** still no devices in WSL2 (expected) — Phase 2 stays headless by
  design (prerecorded/file-based caller audio in, synthesized audio to file,
  no live microphone/speaker).
- **No paid calls were made** in this spike.

Key installed versions (`uv pip list` in the spike venv): pipecat-ai 1.8.1,
pydantic 2.13.5, websockets 17.1, aiohttp 3.14.3, numpy 2.5.3, loguru 0.7.3,
onnxruntime 1.24.4, openai 2.54.0 (transitive dep, unused — no key set).

## Prior entry (2026-09-08: NO-GO, superseded by the retry above)

**NO-GO for tonight (environment only — no Turnstile code is blocked).**
WSL2 itself runs, but the machine has no usable Linux user distro: the only
installed distribution is Docker Desktop's locked-down utility VM, which has
no working Python. Standing up a real distro (Ubuntu download + first-boot
setup, possible reboot/virtualization prompts) is an attended, owner-level
environment decision — not an overnight headless task. Phase 1 (text-mode
agent → ingest, branch `opencode/live-p1-textmode`) does not need this
environment and already landed green.

## What was tried (exact)

```powershell
wsl --list --verbose
# NAME            STATE     VERSION
# * docker-desktop  Stopped   2

wsl --status
# Default Distribution: docker-desktop
# Default Version: 2

wsl -d docker-desktop echo DISTRO-ALIVE
# DISTRO-ALIVE   (WSL2 starts the distro on demand -- the hypervisor works)

wsl -d docker-desktop sh -c "cat /etc/os-release | head -3; which python3 pip pip3 uv; python3 --version"
# PRETTY_NAME="Docker Desktop"
# sh: python3: Permission denied
```

No `python3`/`pip`/`uv` in the utility distro, and executing Python is
denied outright. Pipecat was therefore never installed: there is nothing to
install it *into* yet.

## Caveats recorded for the retry

- **Audio:** even with Ubuntu installed, WSL2 has no audio devices by
  default; Phase 0 only needs a *headless* run (Pipecat text/local-audio
  example bot), so this is not a Phase-0 blocker — but Phase 2 (real voice)
  will need an audio story (WSL2 PulseAudio passthrough or a Linux host).
- **GPU:** irrelevant for Phases 0–1 (no local models involved).
- **Networking:** WSL2 virtual NIC is fine for pip installs and API calls;
  no proxy config was needed or tested.
- **No paid calls were made** in this spike (nothing ran).

## Unblock steps (owner, ~30 attended minutes)

1. `wsl --install Ubuntu` (Store download; may request a reboot for the
   virtualization platform) and complete first-boot user setup.
2. Inside Ubuntu: install `uv` (or Python 3.12 + pip), then
   `pip install pipecat-ai` per Pipecat's quickstart, pinned version TBD.
3. Run Pipecat's minimal text example bot headless; paste the transcript +
   `pip freeze` versions here and flip the verdict to GO.
