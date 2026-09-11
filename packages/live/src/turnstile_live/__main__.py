"""Demo entry: run a scripted conversation, write the ingest call, and print
the pipeline's own verdict/cost for it.

Modes: `text` (default -- free, deterministic: mock policy + mock telemetry)
and `voice --live` (real local Whisper STT + real local Piper TTS + the
capped-LLM policy; STT/TTS free and local, the LLM is owner-gated paid --
`--live` refuses without TURNSTILE_ALLOW_PAID=1)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from turnstile_ingest import run_call
from turnstile_schema import Baselines, load_rates

from turnstile_live.loop import SCRIPTED_DEMO_TURNS, run_conversation

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _report_for(call) -> dict:
    rates = load_rates(_REPO_ROOT / "pricing" / "rates.yaml")
    baselines = Baselines.model_validate_json(
        (_REPO_ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
    )
    return run_call(call.model_dump(mode="json"), rates, baselines)


def _write_callset(out: Path, call) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"calls": [call.model_dump(mode="json")]}, indent=2),
        encoding="utf-8",
    )


def _run_text(args) -> None:
    call = run_conversation(
        call_id=args.call_id, scenario=args.scenario,
        caller_turns=list(SCRIPTED_DEMO_TURNS),
    )
    out = Path(args.out)
    _write_callset(out, call)
    report = _report_for(call)
    print(f"wrote {out}: {len(call.turns)} turns, "
          f"verdict={report['verdict']['label']}, "
          f"cost=${report['conv_cost_usd']:.4f} "
          f"(mock policy + mock telemetry: {call.agent_version})")


def _run_voice(args) -> None:
    import os

    from turnstile_live.voice import (
        CappedLlmPolicy,
        PiperTts,
        WhisperStt,
        run_voice_conversation,
    )

    if not args.live:
        raise SystemExit("--mode voice needs --live (real engines).")
    if os.environ.get("TURNSTILE_ALLOW_PAID") != "1":
        raise SystemExit("--live refuses: set TURNSTILE_ALLOW_PAID=1 (the LLM policy is paid).")
    stt = WhisperStt()
    tts = PiperTts()
    llm = CappedLlmPolicy()
    call, voice_report = run_voice_conversation(
        call_id=args.call_id, scenario=args.scenario,
        caller_texts=list(SCRIPTED_DEMO_TURNS),
        stt=stt, tts=tts, llm=llm, audio_dir=args.audio_dir,
    )
    out = Path(args.out)
    _write_callset(out, call)
    report = _report_for(call)
    fallbacks = sum(1 for t in voice_report["turns"] if t["llm_fallback"])
    print(f"wrote {out}: {len(call.turns)} turns, "
          f"verdict={report['verdict']['label']}, "
          f"cost=${report['conv_cost_usd']:.4f} "
          f"({call.agent_version}; llm_fallbacks={fallbacks})")
    print(f"audio: {args.audio_dir}")
    for note in voice_report["turns"]:
        print(f"  heard={note['heard']!r} decision={note['decision']} "
              f"fallback={note['llm_fallback']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a live demo call.")
    parser.add_argument("--mode", choices=("text", "voice"), default="text")
    parser.add_argument("--out", required=True, help="output ingest-call JSON path")
    parser.add_argument("--call-id", default="live-demo-001")
    parser.add_argument("--scenario", default="billing_dispute")
    parser.add_argument("--audio-dir", default="voice-audio",
                        help="voice mode: where caller/agent wavs go")
    parser.add_argument("--live", action="store_true",
                        help="voice mode: use real Whisper + Piper + capped LLM")
    args = parser.parse_args(argv)
    if args.mode == "voice":
        _run_voice(args)
    else:
        _run_text(args)


if __name__ == "__main__":
    main()
