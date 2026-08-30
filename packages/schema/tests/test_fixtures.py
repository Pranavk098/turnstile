from pathlib import Path
import collections, yaml, pytest
from turnstile_schema import load_trace

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"

REQUIRED_DISTRIBUTION = {
    "baseline": 1, "detector": 10, "multi_waste": 3,
    "escalation": 2, "abandoned": 1, "false_resolve": 1, "edge": 2,
}  # total = 20

def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]

def test_manifest_distribution_matches_required():
    counts = collections.Counter(f["category"] for f in _manifest())
    assert dict(counts) == REQUIRED_DISTRIBUTION

def test_every_manifest_fixture_file_exists():
    for f in _manifest():
        assert (GOLDEN / f["id"]).with_suffix(".json").exists(), f["id"]

@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.name)
def test_fixture_is_schema_valid(path):
    load_trace(path)   # raises ValidationError on any violation
