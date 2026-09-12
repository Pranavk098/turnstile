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
    parser.add_argument("--mode", choices=("text", "voice", "openloop", "bargein"), default="text")
    parser.add_argument("--out", required=True, help="output path (ingest call JSON, or run report JSON)")
    parser.add_argument("--call-id", default="live-demo-001")
    parser.add_argument("--scenario", default="billing_dispute")
    parser.add_argument("--audio-dir", default="voice-audio",
                        help="voice/bargein mode: where caller/agent wavs go")
    parser.add_argument("--live", action="store_true",
                        help="voice/bargein/openloop mode: use real Whisper + Piper / capped LLM (+ judge)")
    parser.add_argument("--n", type=int, default=50,
                        help="bargein mode: TOTAL calls across sweep levels (runtime guard: start at 50)")
    parser.add_argument("--p-levels", default="0.25,0.5,0.75",
                        help="bargein mode: comma-separated per-turn barge-in probabilities to sweep")
    parser.add_argument("--pos-lo", type=float, default=0.25,
                        help="bargein mode: interruption-position window low (audio fraction)")
    parser.add_argument("--pos-hi", type=float, default=0.75,
                        help="bargein mode: interruption-position window high (audio fraction)")
    parser.add_argument("--seed", type=int, default=0,
                        help="bargein mode: determinism seed for caller sampling")
    parser.add_argument("--calls-dir", default=None,
                        help="bargein mode: persist each call's ingest JSON here (post-hoc analysis)")
    parser.add_argument("--policy", choices=("label", "functools"), default="label",
                        help="openloop mode: label-elicitation or function-calling LLM policy")
    parser.add_argument("--scripts", choices=("v24", "v36", "v72"), default="v24",
                        help="openloop mode: P3's 24 probes, +12 Phase-5 probes, or +36 scale probes")
    args = parser.parse_args(argv)
    if args.mode == "voice":
        _run_voice(args)
    elif args.mode == "openloop":
        _run_openloop(args)
    elif args.mode == "bargein":
        _run_bargein(args)
    else:
        _run_text(args)


def _run_openloop(args) -> None:
    from turnstile_live.openloop import (
        EXTRA_SCRIPTS,
        EXTRA_SCRIPTS_2,
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
    convos = list(SCRIPT_SET)
    if args.scripts in ("v36", "v72"):
        convos += list(EXTRA_SCRIPTS)
    if args.scripts == "v72":
        convos += list(EXTRA_SCRIPTS_2)
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


def _run_bargein(args) -> None:
    import time

    from turnstile_live.bargein import (
        BARGE_SCRIPT,
        aggregate_sweep,
        run_bargein_call,
        score_call,
    )
    from turnstile_live.caller import ImpatientCaller
    from turnstile_live.openloop import enforce_budget

    if args.live and os.environ.get("TURNSTILE_ALLOW_PAID") != "1":
        raise SystemExit("--live refuses: set TURNSTILE_ALLOW_PAID=1 (the LLM policy is paid).")
    enforce_budget(n_convos=args.n, turns_each=len(BARGE_SCRIPT))
    if args.live:
        from turnstile_live.voice import CappedLlmPolicy, PiperTts, WhisperStt

        stt: object = WhisperStt()
        tts: object = PiperTts()
        llm: object = CappedLlmPolicy()
        engines = "whisper-tiny.en + piper-lessac + capped-gpt-5-mini"
    else:
        from turnstile_live.fakes import FakeLlm, FakeStt, FakeTts

        tts = FakeTts()
        llm = FakeLlm()
        engines = "fakes (free dry-run)"
    rates = load_rates(_REPO_ROOT / "pricing" / "rates.yaml")
    baselines = Baselines.model_validate_json(
        (_REPO_ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
    )
    p_levels = [float(p) for p in args.p_levels.split(",")]
    per_level = args.n // len(p_levels)
    if per_level < 1:
        raise SystemExit(f"--n {args.n} too small for {len(p_levels)} levels.")
    t0 = time.monotonic()
    cells: dict[str, list] = {}
    counts: dict[str, dict[str, float]] = {}
    verdicts: dict[str, int] = {}
    examples: dict[str, dict] = {}
    in_tok = out_tok = 0
    audio_root = Path(args.audio_dir)
    calls_root = Path(args.calls_dir) if args.calls_dir else None
    if calls_root is not None:
        calls_root.mkdir(parents=True, exist_ok=True)
    for li, p in enumerate(p_levels):
        level = f"p{p:g}"
        cells[level] = []
        counts[level] = {"d6_waste": 0.0, "d8_waste": 0.0, "n_d6": 0, "n_d7": 0, "n_d8": 0}
        for i in range(per_level):
            call_id = f"barge-{level}-{i:03d}"
            caller = ImpatientCaller(
                p_barge=p, pos_lo=args.pos_lo, pos_hi=args.pos_hi,
                seed=args.seed + li * 10000 + i)
            call_stt = stt if args.live else FakeStt(list(BARGE_SCRIPT))
            call, notes = run_bargein_call(
                call_id=call_id, scenario=args.scenario,
                caller_texts=list(BARGE_SCRIPT), caller=caller,
                stt=call_stt,
                tts=tts, llm=llm, audio_dir=audio_root / level,
            )
            call_dict = call.model_dump(mode="json")
            if calls_root is not None:
                (calls_root / f"{call_id}.json").write_text(
                    json.dumps(call_dict), encoding="utf-8")
            scored = score_call(call_dict, rates, baselines)
            verdicts[scored["verdict"]] = verdicts.get(scored["verdict"], 0) + 1
            cells[level].append((scored["d7_waste"], scored["tts_spend"]))
            counts[level]["d6_waste"] += scored["d6_waste"]
            counts[level]["d8_waste"] += scored["d8_waste"]
            counts[level]["n_d6"] += scored["n_d6"]
            counts[level]["n_d7"] += scored["n_d7"]
            counts[level]["n_d8"] += scored["n_d8"]
            for turn_note in notes["turns"]:
                in_tok += turn_note["in_tok"]
                out_tok += turn_note["out_tok"]
            if i == 0:
                examples[level] = {"call_id": call_id, "notes": notes["turns"],
                                   "d7_waste": scored["d7_waste"],
                                   "verdict": scored["verdict"]}
    runtime_s = time.monotonic() - t0
    table = aggregate_sweep(cells)
    for level in table:
        table[level]["d6_waste_usd"] = counts[level]["d6_waste"]
        table[level]["d8_waste_usd"] = counts[level]["d8_waste"]
        table[level]["n_d6_findings"] = counts[level]["n_d6"]
        table[level]["n_d7_findings"] = counts[level]["n_d7"]
        table[level]["n_d8_findings"] = counts[level]["n_d8"]
    pooled = [(w, s) for per in cells.values() for w, s in per]
    from turnstile_live.bargein import d7_share_of_tts_spend

    share, lo, hi = d7_share_of_tts_spend(pooled)
    total_waste = sum(w for w, _s in pooled)
    total_spend = sum(s for _w, s in pooled)
    spend_usd = in_tok / 1e6 * 0.25 + out_tok / 1e6 * 2.00
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "label": "barge-in at volume (MEASURED D7 on real Piper audio) -- separate from "
                 "the harness figure; never folded into the margin.",
        "live": bool(args.live), "engines": engines,
        "config": {"n": per_level * len(p_levels), "p_levels": p_levels,
                   "pos_window": [args.pos_lo, args.pos_hi], "seed": args.seed,
                   "scenario": args.scenario},
        "sweep": table,
        "pooled": {"n_calls": len(pooled), "d7_share": share,
                   "d7_share_ci95": [lo, hi], "d7_waste_usd": total_waste,
                   "tts_spend_usd": total_spend},
        "verdicts": verdicts,
        "usage_tokens": {"input": in_tok, "output": out_tok},
        "spend_usd_metered": spend_usd,
        "runtime_s": runtime_s,
        "examples": examples,
    }, indent=2), encoding="utf-8")
    print(f"wrote {out}: pooled D7 share={share:.2%} [{lo:.2%}, {hi:.2%}] "
          f"over {len(pooled)} calls in {runtime_s:.0f}s "
          f"(metered=${spend_usd:.4f}; verdicts={verdicts})")


if __name__ == "__main__":
    main()
