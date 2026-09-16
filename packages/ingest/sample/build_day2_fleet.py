"""Day-2 committed ingest artifact: 50-call native SAMPLE fleet + the Retell
provider-adapted sample, one mixed report (P0 #3 surfacing).

Reproducible recipe (deterministic -- re-running rewrites byte-identical
files, asserted below):

    uv run python packages/ingest/sample/build_day2_fleet.py

Steps: (1) ``build_fleet.build()`` regenerates ``sample/calls.json`` (seeded;
the bytes MUST match the committed file or the build stops -- the native leg
is frozen); (2) the Retell sample is adapted via ``from_retell_export`` (its
embedded ``agent_model`` ground truth, no flag, no invented model);
(3) ``run_calls`` runs the UNCHANGED pipeline over native + adapted with the
provider record (D1 excluded from measured waste on the inferred call, margin
replay excludes it, provenance carries ``source: Retell export
(synthetic ...)``); (4) ``packages/ingest/data/`` is written (``data.json`` +
per-call files, additive: the 50 native rows are untouched, one Retell row
joins them).

Publish to the dashboard afterwards with ``build_data.build_ingest()`` (its
manifest hook is unchanged -- same status/report_path -- so ``manifest.json``
and every golden file stay byte-identical).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA_DIR = ROOT / "packages" / "ingest" / "data"
NATIVE_PATH = HERE / "calls.json"
RETELL_PATH = HERE / "retell-export.sample.json"

sys.path.insert(0, str(HERE))
import build_fleet  # noqa: E402  (seeded native-fleet authoring)

from turnstile_schema import Baselines, load_rates  # noqa: E402
from turnstile_ingest.adapter import DEFAULT_RATES_PATH  # noqa: E402
from turnstile_ingest.pipeline import DEFAULT_BASELINES_PATH, run_calls  # noqa: E402
from turnstile_ingest.providers import retell as retell_provider  # noqa: E402

LABEL = "ingested sample (50 native + 1 Retell provider-adapted)"


def main() -> int:
    before = NATIVE_PATH.read_bytes()
    build_fleet.build()
    after = NATIVE_PATH.read_bytes()
    if before != after:
        raise SystemExit(
            "sample/calls.json drifted under build_fleet.py (seeded build must be "
            "byte-identical) -- refusing to rebuild the Day-2 artifact on a moved "
            "native leg; investigate before re-running"
        )

    native_obj = json.loads(NATIVE_PATH.read_text(encoding="utf-8"))
    native_calls = native_obj["calls"]
    if len(native_calls) != 50:
        raise SystemExit(
            f"sample/calls.json holds {len(native_calls)} calls, expected the "
            "frozen 50-call native leg"
        )
    retell_raw = json.loads(RETELL_PATH.read_text(encoding="utf-8"))
    if retell_raw.get("sample") is not True:
        raise SystemExit(f"{RETELL_PATH.name}: expected sample:true on the Day-2 input")
    adapted = retell_provider.from_retell_export(retell_raw)
    if len(adapted) != 1:
        raise SystemExit("Retell sample must adapt to exactly one IngestCall")

    rates = load_rates(DEFAULT_RATES_PATH)
    baselines = Baselines.model_validate(
        json.loads(Path(DEFAULT_BASELINES_PATH).read_text(encoding="utf-8")))
    provider_records = {
        call.id: retell_provider.provider_info(raw_obj, call, sample=True)
        for raw_obj, call in zip([retell_raw], adapted)
    }
    artifact, details = run_calls(
        [*native_calls, *adapted], rates, baselines,
        label=LABEL, sample=True, provider=provider_records,
    )
    if artifact["n"] != 51:
        raise SystemExit(f"mixed artifact n={artifact['n']}, expected 51")
    ids = [row["id"] for row in artifact["calls"]]
    if len(set(ids)) != 51 or adapted[0].id not in ids:
        raise SystemExit("mixed artifact call ids are not 51 distinct ids incl. the Retell call")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "data.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    for filename, detail in details.items():
        (DATA_DIR / filename).write_text(json.dumps(detail, indent=2), encoding="utf-8")

    fleet = artifact["fleet"]
    summary = artifact["coverage_summary"]["calls_with_data_per_class"]
    print(f"wrote {DATA_DIR / 'data.json'} + {len(details)} per-call files (n=51)")
    print(f"margin {fleet['recoverable_margin_pct']:.4f}% "
          f"(excluded {artifact['coverage_summary'].get('margin_excluded', 0)} inferred call(s))")
    print("coverage: " + ", ".join(f"D{c}={summary.get(str(c), 0)}/51" for c in range(1, 11)))
    print("provenance: " + artifact["provenance"][:220] + "...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
