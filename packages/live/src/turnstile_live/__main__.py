"""Demo entry: run a scripted conversation, write the ingest call, and print
the pipeline's own verdict/cost for it.

Modes: `text` (default -- free, deterministic: mock policy + mock telemetry),
`voice --live` (real local Whisper STT + real local Piper TTS + the
capped-LLM policy; STT/TTS free and local, the LLM is owner-gated paid --
`--live` refuses without TURNSTILE_ALLOW_PAID=1), and `openloop` (Phase 3:
cheaper-model decisions driven forward to a terminal state; `--live` swaps
the mock policy for the capped LLM + the real judge, budget-guarded)."""
from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument("--mode", choices=("text", "voice", "openloop"), default="text")
    parser.add_argument("--out", required=True, help="output path (ingest call JSON, or openloop report JSON)")
    parser.add_argument("--call-id", default="live-demo-001")
    parser.add_argument("--scenario", default="billing_dispute")
    parser.add_argument("--audio-dir", default="voice-audio",
                        help="voice mode: where caller/agent wavs go")
    parser.add_argument("--live", action="store_true",
                        help="voice/openloop mode: use real engines / capped LLM + judge")
    parser.add_argument("--policy", choices=("label", "functools"), default="label",
                        help="openloop mode: label-elicitation or function-calling LLM policy")
    parser.add_argument("--scripts", choices=("v24", "v36"), default="v24",
                        help="openloop mode: P3's 24 probes, or +12 Phase-5 extension probes")
    args = parser.parse_args(argv)
    if args.mode == "voice":
        _run_voice(args)
    elif args.mode == "openloop":
        _run_openloop(args)
    else:
        _run_text(args)


def _run_openloop(args) -> None:
    from turnstile_live.openloop import (
        EXTRA_SCRIPTS,
        SCRIPT_SET,
        enforce_budget,
        openai_judge_chat,
        rule1_registry,
        rule2_judge,
        run_baseline,
        run_live,
        summarize,
    )
    from turnstile_live.policy import decide as mock_decide
    from turnstile_live.voice import CappedLlmPolicy, FunctionCallingPolicy, LlmDecision

    rates = load_rates(_REPO_ROOT / "pricing" / "rates.yaml")
    convos = list(SCRIPT_SET) + (list(EXTRA_SCRIPTS) if args.scripts == "v36" else [])
    if args.live:
        if os.environ.get("TURNSTILE_ALLOW_PAID") != "1":
            raise SystemExit("--live refuses: set TURNSTILE_ALLOW_PAID=1 (LLM decisions + judge are paid).")
        enforce_budget(n_convos=len(convos), turns_each=3)
        from turnstile_live.voice import LLM_MODEL_DEFAULT

        if args.policy == "functools":
            live_policy = FunctionCallingPolicy()
        else:
            live_policy = CappedLlmPolicy()
        judge = openai_judge_chat(LLM_MODEL_DEFAULT)
    else:
        class _MockPolicy:
            def decide(self, scenario, transcript, turn_index, candidates=None):
                mock = mock_decide(scenario, transcript, turn_index)
                return LlmDecision(mock.decision_kind, mock.decision, mock.reply, 700, 20, True, 0.0)

        live_policy = _MockPolicy()
        judge = None

    rows: list[dict] = []
    in_tok = out_tok = 0
    for conv in convos:
        baseline = run_baseline(conv)
        executed, _call = run_live(conv, live_policy, rates)
        divergent = executed.divergent_from(baseline)
        tools = [(name, effect) for turn in executed.turns for name, effect in turn.tools]
        rule1 = rule1_registry(conv.scenario, tools, executed.verdict_label) if divergent else None
        rule2: bool | None = None
        if divergent and judge is not None:
            transcript = "\n".join(
                f"Caller: {text}\nAgent: {turn.reply}"
                for text, turn in zip(conv.caller_texts, executed.turns)
            )
            rule2, judge_in, judge_out = rule2_judge(judge, conv.scenario, transcript)
            in_tok += judge_in
            out_tok += judge_out
        for turn in executed.turns:
            in_tok += turn.input_tokens
            out_tok += turn.output_tokens
        rows.append({
            "id": conv.id, "scenario": conv.scenario,
            "baseline_path": [list(d) for d in baseline.decisions],
            "live_path": [list(d) for d in executed.decision_path()],
            "divergent": divergent,
            "verdict": executed.verdict_label,
            "rule1": rule1, "rule2": rule2,
            "replies": [t.reply for t in executed.turns],
        })
    figures = summarize(rows)
    # Spend from metered usage at mini rates ($0.25/$2.00 per M). Meaningful
    # for --live (real usage); mock tokens in the free dry-run.
    spend_usd = in_tok / 1e6 * 0.25 + out_tok / 1e6 * 2.00
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "label": "open-loop preservation-under-divergence (MEASURED) -- separate from "
                 "identity-preservation and from the modeled oracle; never folded.",
        "live": bool(args.live),
        "figures": figures,
        "usage_tokens": {"input": in_tok, "output": out_tok},
        "spend_usd_metered": spend_usd,
        "rows": rows,
    }, indent=2), encoding="utf-8")
    print(f"wrote {out}: registry={figures['registry']} "
          f"llm_judge={figures['llm_judge']} "
          f"(n_divergent={figures['n_divergent']}, "
          f"n_undecidable={figures['n_undecidable']}, "
          f"metered=${spend_usd:.4f})")


if __name__ == "__main__":
    main()
