from pathlib import Path
import collections, json, math, yaml, pytest
from pydantic import ValidationError
from turnstile_schema import load_trace, load_rates
from turnstile_schema.spans import ToolCall

GOLDEN = Path(__file__).parents[3] / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"
RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

REQUIRED_DISTRIBUTION = {
    "baseline": 1, "detector": 10, "multi_waste": 3,
    "escalation": 2, "abandoned": 1, "false_resolve": 1, "edge": 2,
    "effect_edge": 3,
}  # total = 23

# Fixtures deliberately authored with genuine TTS/LLM (or LLM/playback) overlap
# for the Detector 8 union proof -- excluded from the strict non-overlap
# residual == union-gap invariant below.
OVERLAP_FIXTURES = {"00_baseline_clean", "19_edge_40_turn"}

def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["fixtures"]

def test_manifest_distribution_matches_required():
    counts = collections.Counter(f["category"] for f in _manifest())
    assert dict(counts) == REQUIRED_DISTRIBUTION

def test_every_manifest_fixture_file_exists():
    for f in _manifest():
        assert (GOLDEN / f["id"]).with_suffix(".json").exists(), f["id"]

def test_every_manifest_fixture_has_expected_verdict():
    for f in _manifest():
        assert f.get("expected_verdict"), f["id"]

@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.name)
def test_fixture_is_schema_valid(path):
    load_trace(path)   # raises ValidationError on any violation


# ---- v1.1: effect x tool_kind x tool_status validator ----

def _tool_kwargs(**overrides):
    base = {
        "span_id": "s1",
        "turnstile.start_offset_ms": 0, "turnstile.duration_ms": 100,
        "turnstile.tool_name": "some_tool",
        "turnstile.args_hash": "sha256:aa", "turnstile.args_json": "{}",
        "turnstile.result_hash": "sha256:bb", "turnstile.latency_ms": 100,
        "turnstile.tool_kind": "mutation"}
    base.update(overrides)
    return base

@pytest.mark.parametrize("overrides", [
    {"turnstile.tool_kind": "handoff", "turnstile.effect": "none"},
    {"turnstile.tool_kind": "mutation", "turnstile.effect": "none"},
    {"turnstile.tool_kind": "lookup", "turnstile.effect": "committed"},
], ids=["handoff+none", "mutation+none", "lookup+committed"])
def test_illegal_effect_tool_kind_combination_raises(overrides):
    with pytest.raises(ValidationError):
        ToolCall.model_validate(_tool_kwargs(**overrides))


# ---- v1.1: Detector 8 invariant -- residual-silence == union-gap-silence on
# non-overlapping fixtures; the overlap fixtures diverge by exactly the
# overlap (the double-count the old sum-based formula introduces). ----

def _covered_intervals_and_billed(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    intervals = []
    for turn in data["turns"]:
        for kind in ("asr", "llm", "tools", "tts", "playback"):
            for span in turn.get(kind, []):
                start = span["turnstile.start_offset_ms"]
                dur = span["turnstile.duration_ms"]
                intervals.append((start, start + dur))
    billed_wall_ms = data["telephony"]["turnstile.billable_seconds"] * 1000
    return intervals, billed_wall_ms

def _union_size(intervals):
    ivs = sorted(intervals)
    total, cur_s, cur_e = 0, None, None
    for s, e in ivs:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    if cur_s is not None:
        total += cur_e - cur_s
    return total

@pytest.mark.parametrize(
    "path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.name)
def test_d8_residual_vs_union_silence_invariant(path):
    intervals, billed_wall_ms = _covered_intervals_and_billed(path)
    summed = sum(e - s for s, e in intervals)
    union = _union_size(intervals)
    residual_silence = billed_wall_ms - summed
    union_gap_silence = billed_wall_ms - union
    overlap_ms = summed - union
    if path.stem in OVERLAP_FIXTURES:
        assert overlap_ms > 0, f"{path.stem} is flagged as an overlap fixture but has none"
        assert residual_silence != union_gap_silence
        assert union_gap_silence - residual_silence == overlap_ms
    else:
        assert overlap_ms == 0, f"{path.stem} has unexpected span overlap"
        assert residual_silence == union_gap_silence


# ---- rate-key resolution guard: every priced span in every fixture must resolve
# to a real pricing/rates.yaml entry under the documented convention (see the
# comment block at the top of rates.yaml) -- asr/llm: f"{system}/{model}" (bare
# model, no provider prefix); tts: system alone (TtsSynthesize has no model
# field); telephony.leg: f"{provider}/pstn_{direction}". This is the check that
# would have caught fixtures authored with rate-key-incompatible strings. ----

@pytest.mark.parametrize(
    "path", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.name)
def test_every_priced_span_resolves_to_a_rate(path):
    rt = load_rates(RATES)
    data = json.loads(path.read_text(encoding="utf-8"))

    for turn in data["turns"]:
        for span in turn.get("asr", []):
            key = f'{span["gen_ai.system"]}/{span["gen_ai.request.model"]}'
            assert key in rt.asr, f"{path.name}: asr key {key!r} not in rates.yaml"
        for span in turn.get("llm", []):
            key = f'{span["gen_ai.system"]}/{span["gen_ai.request.model"]}'
            assert key in rt.llm, f"{path.name}: llm key {key!r} not in rates.yaml"
        for span in turn.get("tts", []):
            key = span["gen_ai.system"]
            assert key in rt.tts, f"{path.name}: tts key {key!r} not in rates.yaml"

    telephony = data.get("telephony")
    if telephony:
        key = f'{telephony["turnstile.provider"]}/pstn_{telephony["turnstile.direction"]}'
        assert key in rt.telephony, f"{path.name}: telephony key {key!r} not in rates.yaml"
