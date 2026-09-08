"""Demo entry: run the bundled scripted conversation, write the ingest call,
and print the pipeline's own verdict/cost for it (free, deterministic)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from turnstile_ingest import run_call
from turnstile_schema import Baselines, load_rates

from turnstile_live.loop import SCRIPTED_DEMO_TURNS, run_conversation

_REPO_ROOT = Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the text-mode demo call.")
    parser.add_argument("--out", required=True, help="output ingest-call JSON path")
    parser.add_argument("--call-id", default="live-demo-001")
    parser.add_argument("--scenario", default="billing_dispute")
    args = parser.parse_args(argv)

    call = run_conversation(
        call_id=args.call_id, scenario=args.scenario,
        caller_turns=list(SCRIPTED_DEMO_TURNS),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"calls": [call.model_dump(mode="json")]}, indent=2),
        encoding="utf-8",
    )
    rates = load_rates(_REPO_ROOT / "pricing" / "rates.yaml")
    baselines = Baselines.model_validate_json(
        (_REPO_ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
    )
    report = run_call(call.model_dump(mode="json"), rates, baselines)
    print(f"wrote {out}: {len(call.turns)} turns, "
          f"verdict={report['verdict']['label']}, "
          f"cost=${report['conv_cost_usd']:.4f} "
          f"(mock policy + mock telemetry: {call.agent_version})")


if __name__ == "__main__":
    main()
