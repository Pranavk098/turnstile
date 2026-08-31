"""THE hard acceptance gate for packages/detectors.

Fixtures are engineered so that a naive "fires on everything" detector would
pass ordinary positive tests. The real gate is the false-positive rate: for
each of the five deterministic classes {2, 6, 7, 8, 10}, this fires on every
fixture manifest.yaml names as a target for that class, AND is silent on
every one of the other fixtures -- the clean baseline included.

Multi-waste fixtures 11/12/13 legitimately combine several classes and are
parsed straight from manifest.yaml's `target_detector: "1,2,8"` style field,
so no class list is hand-duplicated here.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from turnstile_schema import Baselines, Verdict, load_rates, load_trace
from turnstile_schema.enums import VerdictLabel
from turnstile_pricing import price_trace
from turnstile_detectors import detect

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

DETECTOR_CLASSES = (2, 6, 7, 8, 10)

_DUMMY_VERDICT = Verdict(label=VerdictLabel.RESOLVED, confidence=1.0, evidence=[], turn_of_no_return=None)
_EMPTY_BASELINES = Baselines(per_intent={})


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
    findings = detect(priced, _DUMMY_VERDICT, _EMPTY_BASELINES)
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
