# LIVE-AGENT — environment log (Phase 0 spike, 2026-09-08)

## Go / no-go

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
