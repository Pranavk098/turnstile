"""THE hard acceptance gate for packages/detectors.

Fixtures are engineered so that a naive "fires on everything" detector would
pass ordinary positive tests. The real gate is the false-positive rate: for
each of the ten classes {1..10}, this fires on every fixture manifest.yaml
names as a target for that class, AND is silent on every one of the other
fixtures -- the clean baseline included.

Multi-waste fixtures 11/12/13 legitimately combine several classes and are
parsed straight from manifest.yaml's `target_detector: "1,2,8"` style field,
so no class list is hand-duplicated here.

Batch A's five deterministic classes {2, 6, 7, 8, 10} never read `verdict` or
`baselines` (they were built against a dummy always-RESOLVED verdict and empty
baselines and still passed this gate). Batch B's five judgment classes
{1, 3, 4, 5, 9} do: Detector 4 needs real `Baselines.per_intent` entries
(fixtures/sample/baselines.json, see its calibration note in the Wave report)
or it can never fire, and Detector 9 needs a real `Verdict.label`/
`turn_of_no_return` (a dummy always-RESOLVED verdict makes tier 1's
`label == ESCALATED` guard permanently false) -- so this sweep now adjudicates
every fixture for real via `turnstile_verdict.adjudicate` instead of reusing a
dummy verdict, and loads the calibrated sample baselines instead of an empty
table. This does not violate "use the verdict arg detect() already provides,
don't re-adjudicate unless a test needs to" (packages/detectors/tests/
_builders.py's DUMMY_VERDICT remains correct for the per-detector unit tests,
which construct their own minimal traces and don't need real adjudication) --
the full 10-class sweep against real fixtures is exactly the case that does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from turnstile_schema import Baselines, load_rates, load_trace
from turnstile_pricing import price_trace
from turnstile_verdict import adjudicate
from turnstile_detectors import detect

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"
SAMPLE_BASELINES = Path(__file__).parents[3] / "fixtures" / "sample" / "baselines.json"

DETECTOR_CLASSES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)

_BASELINES = Baselines.model_validate(json.loads(SAMPLE_BASELINES.read_text(encoding="utf-8")))


def _manifest_fixtures() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]


def _targets_for_class(class_id: int) -> set[str]:
    targets = set()
    for entry in _manifest_fixtures():
        raw = entry["target_detector"]
        ids = {int(x) for x in str(raw).split(",")} if raw != "none" else set()
        if class_id in ids:
            targets.add(entry["id"])
    return targets


def _fired_classes(fid: str) -> set[int]:
    trace = load_trace((GOLDEN / fid).with_suffix(".json"))
    priced = price_trace(trace, load_rates(RATES))
    verdict = adjudicate(priced)
    findings = detect(priced, verdict, _BASELINES)
    return {f.class_id for f in findings}


# Cache fired-class sets across the whole sweep -- 23 fixtures x 5 classes
# would otherwise re-run detect() 115 times.
@pytest.fixture(scope="module")
def fired_by_fixture() -> dict[str, set[int]]:
    return {entry["id"]: _fired_classes(entry["id"]) for entry in _manifest_fixtures()}


@pytest.mark.parametrize("class_id", DETECTOR_CLASSES)
def test_fires_on_every_target_fixture(class_id, fired_by_fixture):
    targets = _targets_for_class(class_id)
    assert targets, f"class {class_id} has no target fixtures in manifest.yaml"
    for fid in targets:
        assert class_id in fired_by_fixture[fid], (
            f"detector {class_id} did not fire on its target fixture {fid} "
            f"(fired classes: {sorted(fired_by_fixture[fid])})"
        )


@pytest.mark.parametrize("class_id", DETECTOR_CLASSES)
def test_silent_on_every_non_target_fixture(class_id, fired_by_fixture):
    targets = _targets_for_class(class_id)
    non_targets = [entry["id"] for entry in _manifest_fixtures() if entry["id"] not in targets]
    assert non_targets
    for fid in non_targets:
        assert class_id not in fired_by_fixture[fid], (
            f"detector {class_id} false-fired on non-target fixture {fid} "
            f"(fired classes: {sorted(fired_by_fixture[fid])})"
        )
