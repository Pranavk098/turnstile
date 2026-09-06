"""Tests for the dashboard's data builder (batch 2 T3/T4, W3-B Items 1-2).

The load-bearing assertions: the barge-in panel's numbers TRACE to the
harness report (nothing recomputed or hardcoded), per-call data traces to
the real pipeline over every golden fixture, and the build writes ONLY
data -- running it modifies no .html file."""
from __future__ import annotations

import json

import pytest
from turnstile_corpus.distributions import BARGE_IN_RATE
from turnstile_agent import FakeEngine
from turnstile_experiments import run_bargein_report

import build_data


# --------------------------------------------------------------------------- #
# The barge-in headline panel traces to the harness report.                    #
# --------------------------------------------------------------------------- #

def _small_report(**kwargs):
    return run_bargein_report(
        FakeEngine(), rates_values=[0.0, BARGE_IN_RATE, 0.3], n=12, seed=3, **kwargs)


def test_bargein_panel_traces_to_the_report_verbatim():
    report = _small_report()
    panel = build_data.build_bargein(report)
    # Nothing recomputed: every table IS the report's own data.
    assert panel["rate_sweep"] == report["points"]
    assert panel["lead_cap_sweep"] == report["lead_cap_sweep"]
    assert panel["granularity_sweep"] == report["granularity_sweep"]
    assert panel["provenance"] == report["provenance"]
    assert panel["n"] == report["n"] and panel["seed"] == report["seed"]
    # The headline IS the report's point at the cited default rate.
    assert panel["headline"] == next(
        p for p in report["points"] if p["barge_in_rate"] == BARGE_IN_RATE)
    assert panel["headline"]["waste_share_of_tts_spend"] > 0.0
    assert "measured" in panel["label"].lower()


def test_bargein_panel_requires_the_cited_rate_point():
    report = run_bargein_report(FakeEngine(), rates_values=[0.05, 0.10], n=6, seed=1)
    with pytest.raises(ValueError, match="cited default rate"):
        build_data.build_bargein(report)


def test_bargein_panel_floor_annotation_comes_from_the_report_points():
    report = _small_report()
    panel = build_data.build_bargein(report)
    fl = panel["floor_annotation"]
    if fl is not None:  # a flat run exists in this report -> it must trace
        pts = report["lead_cap_sweep"]["points"]
        assert any(
            p["lead_cap_s"] == fl["from"] and p["waste_share_of_tts_spend"] == fl["value"]
            for p in pts
        )
        assert fl["to"] >= fl["from"]
        assert "floor" in fl["note"]


def test_flat_run_detector_finds_the_measured_floor():
    points = [
        {"lead_cap_s": 0.5, "waste_share_of_tts_spend": 0.041},
        {"lead_cap_s": 1.0, "waste_share_of_tts_spend": 0.041},
        {"lead_cap_s": 2.0, "waste_share_of_tts_spend": 0.041},
        {"lead_cap_s": 3.0, "waste_share_of_tts_spend": 0.044},
    ]
    fl = build_data._flat_run(points, "lead_cap_s", "waste_share_of_tts_spend")
    assert fl == {
        "from": 0.5, "to": 2.0, "value": 0.041,
        "note": build_data._flat_run(points, "lead_cap_s", "waste_share_of_tts_spend")["note"],
    }
    assert build_data._flat_run(points[:1], "lead_cap_s", "waste_share_of_tts_spend") is None


def test_load_bargein_report_fails_loud_when_missing(tmp_path):
    with pytest.raises(SystemExit, match="run_bargein_harness"):
        build_data.load_bargein_report(tmp_path / "missing.json")


# --------------------------------------------------------------------------- #
# index.html: the panel exists and the embedded file:// fallback stays in sync.#
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# W3-B Item 1: the build writes ONLY data -- index.html is hand-authored and  #
# fetches sample/*.json. Running build_data.py must modify no .html file.    #
# --------------------------------------------------------------------------- #

def test_build_module_has_no_html_writing_path():
    # Regression guard: the old index.html-rewriting path is gone for good.
    assert not hasattr(build_data, "sync_embedded_json")
    assert not hasattr(build_data, "_EMBED_IDS")
    assert not hasattr(build_data, "INDEX_HTML")


def test_index_html_fetches_data_and_carries_no_embeds():
    html = (build_data.DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="bargein"' in html
    assert "renderBargein(" in html
    assert "sample/bargein.sample.json" in html
    # No embedded fallback copies: the dashboard renders purely from fetched JSON.
    assert "application/json" not in html
    assert "data-bargein" not in html


def test_build_main_modifies_no_html_file(tmp_path, monkeypatch):
    import hashlib

    dashboard = build_data.DASHBOARD_DIR
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(dashboard.glob("*.html"))
    }
    assert before, "expected hand-authored html next to build_data.py"
    monkeypatch.setattr(build_data, "SAMPLE_DIR", tmp_path)
    build_data.main()
    # All six fleet datasets are still written as data ...
    for name in ("priced_trace.json", "fleet.json", "findings.sample.json",
                 "experiments.sample.json", "bargein.sample.json",
                 "conditional.sample.json"):
        assert (tmp_path / name).exists(), name
    # ... and no .html file changed.
    after = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(dashboard.glob("*.html"))
    }
    assert after == before


# --------------------------------------------------------------------------- #
# T4: the conditional-savings panel — run_repricing_matrix's output, verbatim #
# label, never mixed with the gated proven margin.                            #
# --------------------------------------------------------------------------- #

def test_conditional_panel_traces_to_run_repricing_matrix():
    from turnstile_experiments import REPRICING_VARIANTS, run_repricing_matrix

    rates = build_data.load_rates(build_data.RATES_PATH)
    corpus = [build_data.price_trace(build_data.load_trace(p), rates)
              for p in build_data._golden_fixtures()]
    panel = build_data.build_conditional_savings(rates, corpus)
    # The rows ARE the runner's own output (nothing recomputed or massaged):
    # recompute here and require exact equality.
    expected = run_repricing_matrix(corpus, REPRICING_VARIANTS, rates=rates)
    assert set(panel["variants"]) == set(REPRICING_VARIANTS)
    for name, r in expected.items():
        row = panel["variants"][name]
        assert row["n"] == r.n
        assert row["delta_cost_mean"] == pytest.approx(r.delta_cost_mean)
        assert row["savings_usd"] == pytest.approx(-r.delta_cost_mean)
        assert row["label"] == r.label
    assert panel["total_savings_usd"] == pytest.approx(
        sum(-r.delta_cost_mean for r in expected.values()))
    assert panel["n_fixtures"] == len(corpus)


def test_conditional_panel_carries_the_label_verbatim_and_stays_separate():
    from turnstile_experiments import CONDITIONAL_SAVINGS_LABEL

    rates = build_data.load_rates(build_data.RATES_PATH)
    corpus = [build_data.price_trace(build_data.load_trace(p), rates)
              for p in build_data._golden_fixtures()]
    panel = build_data.build_conditional_savings(rates, corpus)
    # The label verbatim, in the panel data AND on every row.
    assert panel["label_verbatim"] == (
        "deterministic conditional saving — preservation unverified (Wave-2)")
    assert panel["label_verbatim"] == CONDITIONAL_SAVINGS_LABEL
    assert all(v["label"] == CONDITIONAL_SAVINGS_LABEL
               for v in panel["variants"].values())
    # Textually separate from the gated proven margin: the panel carries no
    # recoverable-margin field, and its provenance forbids the mixing.
    assert "recoverable_margin" not in json.dumps(panel)
    # Forbids mixing with the gated proven margin (per-dataset framing — no
    # hardcoded cross-dataset number; see the margin-reconciliation decision).
    assert "NEVER" in panel["_provenance"] and "gated recoverable margin" in panel["_provenance"]
    assert "H-1" in panel["_provenance"]


def test_conditional_panel_covers_every_remedy_detector():
    rates = build_data.load_rates(build_data.RATES_PATH)
    corpus = [build_data.price_trace(build_data.load_trace(p), rates)
              for p in build_data._golden_fixtures()]
    panel = build_data.build_conditional_savings(rates, corpus)
    detectors = {v["detector"] for v in panel["variants"].values()}
    for marker in ("D2", "D3", "D4", "D9", "D10"):
        assert any(marker in d for d in detectors), marker


def test_index_html_carries_the_conditional_panel():
    html = (build_data.DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="conditional"' in html
    assert "renderConditional(" in html
    assert "sample/conditional.sample.json" in html
    assert "data-conditional" not in html
    # Visually + textually separated: the heading itself carries the label.
    assert "preservation unverified (Wave-2)" in html
    assert "NOT the proven margin" in html


# --------------------------------------------------------------------------- #
# W3-B Item 2 -- per-call data for ALL calls traces to the real pipeline.     #
# --------------------------------------------------------------------------- #

def _rates_and_baselines():
    rates = build_data.load_rates(build_data.RATES_PATH)
    baselines = build_data.Baselines.model_validate(
        json.loads(build_data.BASELINES_PATH.read_text(encoding="utf-8")))
    return rates, baselines


def test_calls_index_covers_every_golden_fixture():
    rates, baselines = _rates_and_baselines()
    index, _ = build_data.build_calls(rates, baselines)
    assert [row["id"] for row in index] == [
        p.stem for p in build_data._golden_fixtures()]
    for row in index:
        assert row["cost_usd"] > 0
        assert row["n_turns"] > 0
        assert row["verdict"] in ("RESOLVED", "PARTIALLY_RESOLVED", "UNRESOLVED",
                                    "ESCALATED", "ABANDONED", "MISROUTED", "FALSE_RESOLVE")
        assert row["detail"] == f"call-{row['id']}.json"


def test_calls_index_traces_to_the_pipeline():
    rates, baselines = _rates_and_baselines()
    index, details = build_data.build_calls(rates, baselines)
    # Spot-check the hero fixture end to end: cost, verdict, top waste all
    # recomputed here from the pipeline must match the built rows.
    hero = next(r for r in index if r["id"] == build_data.HERO_FIXTURE)
    path = build_data.GOLDEN / f"{build_data.HERO_FIXTURE}.json"
    priced, verdict, findings = build_data._analyze(path, rates, baselines)
    assert hero["cost_usd"] == pytest.approx(priced.conv_cost)
    assert hero["verdict"] == verdict.label.value
    assert hero["n_turns"] == len(priced.trace.turns)
    if findings:
        top = max(findings, key=lambda f: f["waste_usd"])
        assert hero["top_waste"]["class_id"] == top["class_id"]
        assert hero["top_waste"]["waste_usd"] == pytest.approx(top["waste_usd"])
    else:
        assert hero["top_waste"] is None
    # Index costs sum to the fleet total (same priced objects, no second math).
    fleet = build_data.build_fleet(
        rates, baselines, build_data.build_experiments(rates)[0])
    assert sum(r["cost_usd"] for r in index) == pytest.approx(fleet["total_cost_usd"])


def test_call_detail_files_carry_the_drill_down_shape():
    rates, baselines = _rates_and_baselines()
    _, details = build_data.build_calls(rates, baselines)
    assert len(details) == len(build_data._golden_fixtures())
    for call_id, data in details.items():
        # Everything the detail view renders: flame graph, verdict, findings.
        for key in ("trace", "span_costs", "turn_costs", "conv_cost",
                    "stage_costs", "verdict", "findings"):
            assert key in data, (call_id, key)
        assert data["_provenance"]["fixture"] == call_id
        assert abs(sum(data["stage_costs"].values()) - data["conv_cost"]) < 1e-9


def test_build_main_writes_per_call_data(tmp_path, monkeypatch):
    monkeypatch.setattr(build_data, "SAMPLE_DIR", tmp_path)
    build_data.main()
    payload = json.loads((tmp_path / "calls.json").read_text(encoding="utf-8"))
    assert payload["n"] == len(build_data._golden_fixtures())
    assert len(payload["calls"]) == payload["n"]
    assert payload["hero"] == build_data.HERO_FIXTURE
    assert any(row["id"] == payload["hero"] for row in payload["calls"])
    for row in payload["calls"]:
        detail = json.loads((tmp_path / row["detail"]).read_text(encoding="utf-8"))
        assert detail["conv_cost"] == pytest.approx(row["cost_usd"])


# --------------------------------------------------------------------------- #
# W3-B Item 5 hook -- manifest.json: source declaration + the ingest slot.    #
# --------------------------------------------------------------------------- #

def test_build_main_writes_manifest_with_ingest_hook(tmp_path, monkeypatch):
    monkeypatch.setattr(build_data, "SAMPLE_DIR", tmp_path)
    build_data.main()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "golden-fixtures"
    assert manifest["calls_index"] == "sample/calls.json"
    assert manifest["hero"] == build_data.HERO_FIXTURE
    assert manifest["n_calls"] == len(build_data._golden_fixtures())
    hook = manifest["ingest"]
    # W3 Item 5 wired: the committed ingest artifact is published into
    # sample/ and the hook points at it (no hardcoded numbers -- the build
    # copies the artifact verbatim, asserted in test_ingest_wire.py).
    assert hook["status"] == "available"
    assert hook["report_path"] == "sample/ingest.json"
    assert (tmp_path / "ingest.json").exists()
    contract = hook["contract"]
    assert set(contract["report_envelope"]) == {"label", "n", "note", "provenance"}
    assert "call-<id>.json" in contract["per_call_files"]
    assert "verdict" in contract["index_row_keys"] and "detail" in contract["index_row_keys"]
    assert "verdict" in contract["detail_keys"] and "findings" in contract["detail_keys"]
    assert "D6/D7/D8" in contract["acoustic_rule"]


def test_build_ingest_returns_none_when_artifact_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(build_data, "INGEST_SOURCE_FILE", tmp_path / "missing.json")
    assert build_data.build_ingest(tmp_path) is None
    manifest = build_data.build_manifest([], None)
    assert manifest["ingest"]["report_path"] is None
    assert "W3-A" in manifest["ingest"]["status"]