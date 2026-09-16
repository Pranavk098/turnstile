"""Async experiment jobs: lifecycle, bounds, eviction, gate agreement, $0 guard.

Uses real TestClient endpoints for submit/poll (proving the wire) plus a
local JobStore for deterministic unit control of caps/TTL. Workloads stay
tiny (1 call) so polling converges in milliseconds.
"""
from __future__ import annotations

import asyncio
import copy
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from turnstile_replay import MockBackend, experiment, get_backend
from turnstile_schema import ExperimentResult, VariantSpec
from turnstile_service.app import MAX_CALLS, _engine, _price_calls, app
from turnstile_service.jobs import JobStore, JobStoreFull, passes_gate, run_experiment_job

# NOTE: background tasks only outlive their request on ONE portal loop, so
# these tests must share a context-managed client per test (a bare
# TestClient spins a fresh event loop per request and strands background
# tasks when it closes). Production (uvicorn) runs one loop forever.
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def live_client():
    with TestClient(app) as client:
        yield client


def _doc_example() -> dict:
    text = (ROOT / "docs" / "INGEST.md").read_text(encoding="utf-8")
    fence = text.split("## The object")[1].split("```json")[1].split("```")[0]
    return json.loads(fence)


def _route_variant() -> dict:
    return {"model_routing": {"route": "gpt-5-nano"}}


def _submit(client, calls, variant=None):
    body = {"calls": calls,
            "variant": variant if variant is not None else _route_variant()}
    return client.post("/api/experiments", json=body)


def _poll_to_done(client, job_id, timeout_s=15.0):
    import time

    deadline = time.monotonic() + timeout_s
    while True:
        res = client.get(f"/api/experiments/{job_id}")
        assert res.status_code == 200, res.text
        status = res.json()["status"]
        assert status in ("queued", "running", "done", "error"), status
        if status in ("done", "error"):
            return res.json()
        assert time.monotonic() < deadline, "job never finished"
        time.sleep(0.02)


def test_submit_poll_done_matches_cli_experiment(live_client):
    """Submit -> poll -> done; result equals the CLI experiment path
    (same calls+variant through map_trials+aggregate_experiment)."""
    call = _doc_example()
    res = _submit(live_client, [call])
    assert res.status_code == 202
    submitted = res.json()
    assert submitted["status"] == "queued" and submitted["job_id"]
    final = _poll_to_done(live_client, submitted["job_id"])
    assert final["status"] == "done"

    rates, _ = _engine()
    expected_obj = experiment(_price_calls([call], rates),
                              VariantSpec.model_validate(_route_variant()))
    assert final["result"]["experiment"] == expected_obj.model_dump(mode="json")
    assert final["result"]["variant"] == {"model_routing": {"route": "gpt-5-nano"}}
    assert final["result"]["n_calls"] == 1
    assert "MockBackend" in final["result"]["provenance"]["note"]
    assert final["result"]["passes_gate"] == passes_gate(expected_obj)
    assert final["n_calls"] == 1


def test_identical_jobs_are_deterministic(live_client):
    """Two identical submissions converge on byte-identical results
    (job ids naturally differ; everything else must not)."""
    first = _poll_to_done(live_client, _submit(live_client, [_doc_example()]).json()["job_id"])
    second = _poll_to_done(live_client, _submit(live_client, [_doc_example()]).json()["job_id"])
    assert first["status"] == second["status"] == "done"
    assert first["result"] == second["result"]


def test_empty_variant_is_valid_identity_sweep(live_client):
    """A VariantSpec with no knobs set is executable (identity replay) --
    not a 422. Nothing to reroute, so the gate stays shut."""
    res = live_client.post("/api/experiments",
                           json={"calls": [_doc_example()], "variant": {}})
    assert res.status_code == 202
    final = _poll_to_done(live_client, res.json()["job_id"])
    assert final["status"] == "done"
    assert final["result"]["passes_gate"] is False


def test_submit_rejects_bad_input_without_engine_run(live_client):
    bad = _doc_example()
    bad["turns"][0]["llm"]["input_tokkens"] = bad["turns"][0]["llm"].pop("input_tokens")
    res = _submit(live_client, [bad])
    assert res.status_code == 422
    assert "turns[0].llm.input_tokens" in res.json()["detail"]
    res = live_client.post("/api/experiments",
                           json={"calls": [_doc_example()],
                                 "variant": {"model_routing": {"route": 42}}})
    assert res.status_code == 422
    res = live_client.post("/api/experiments", json=[_doc_example()])
    assert res.status_code == 422


def test_submit_caps_match_evaluate(live_client):
    big = {"calls": [_doc_example()], "variant": _route_variant(),
           "pad": "x" * (1_000_000 + 1)}
    assert live_client.post("/api/experiments", json=big).status_code == 413
    many = []
    for i in range(MAX_CALLS + 1):
        dup = copy.deepcopy(_doc_example())
        dup["id"] = f"call-flood-{i:03d}"
        many.append(dup)
    assert _submit(live_client, many).status_code == 413


def test_unknown_job_id_is_404(live_client):
    assert live_client.get("/api/experiments/does-not-exist").status_code == 404
    assert live_client.get("/api/experiments/../app").status_code in (404, 422)


def test_store_evicts_expired_and_caps_storage():
    async def _run():
        store = JobStore(max_running=4, max_active=8, max_stored=2, ttl_seconds=-1.0)
        job = store.submit(variant={}, n_calls=0, rates_sha="r", baselines_sha="b",
                           run=lambda: {"ok": True})
        assert store.get(job.job_id) is None  # negative TTL: already expired
        store2 = JobStore(max_running=4, max_active=8, max_stored=1, ttl_seconds=3600)
        first = store2.submit(variant={}, n_calls=0, rates_sha="r", baselines_sha="b",
                              run=lambda: {"ok": True})
        for _ in range(1000):  # let the first job finish (deterministic gate)
            record = store2.get(first.job_id)
            if record is not None and record.status == "done":
                break
            await asyncio.sleep(0.005)
        second = store2.submit(variant={}, n_calls=0, rates_sha="r", baselines_sha="b",
                               run=lambda: {"ok": True})
        assert store2.get(first.job_id) is None  # oldest finished evicted past cap
        assert store2.get(second.job_id) is not None

    asyncio.run(_run())


def test_store_rejects_past_active_cap_without_running_engine():
    started = threading.Event()
    release = threading.Event()

    def _blocked():
        started.set()
        assert release.wait(timeout=10)
        return {"ok": True}

    async def _run():
        store = JobStore(max_running=1, max_active=1, max_stored=8, ttl_seconds=3600)
        first = store.submit(variant={}, n_calls=0, rates_sha="r", baselines_sha="b",
                             run=_blocked)
        for _ in range(1000):  # wait until it holds the running slot
            record = store.get(first.job_id)
            if record is not None and record.status == "running":
                break
            await asyncio.sleep(0.005)
        else:
            pytest.fail("blocked job never started")
        with pytest.raises(JobStoreFull):
            store.submit(variant={}, n_calls=0, rates_sha="r", baselines_sha="b",
                         run=lambda: {"ok": True})
        release.set()
        for _ in range(1000):
            record = store.get(first.job_id)
            if record is not None and record.status == "done":
                break
            await asyncio.sleep(0.005)
        assert store.get(first.job_id).status == "done"

    asyncio.run(_run())


def test_passes_gate_agrees_with_canonical_gate():
    """The service's mirrored gate must equal turnstile_experiments' own."""
    from turnstile_experiments.margin import _passes_gate as canonical

    cases = [
        dict(outcome_preservation_rate=1.0, delta_cost_mean=-0.1,
             delta_cost_ci95=(-0.2, -0.05)),
        dict(outcome_preservation_rate=0.9, delta_cost_mean=-0.1,
             delta_cost_ci95=(-0.2, -0.05)),
        dict(outcome_preservation_rate=1.0, delta_cost_mean=0.1,
             delta_cost_ci95=(0.05, 0.2)),
        dict(outcome_preservation_rate=0.0, delta_cost_mean=0.0,
             delta_cost_ci95=(0.0, 0.0)),
    ]
    for kwargs in cases:
        result = ExperimentResult(
            n=10, delta_latency_p50=0.0, delta_latency_p95=0.0,
            divergent_exemplars=[], **kwargs)
        assert passes_gate(result) == canonical(result)


def test_job_refuses_non_mock_backend(live_client, monkeypatch):
    """$0 guard: a paid backend set globally must error the job, never run it."""
    class _Paid:
        pass

    monkeypatch.setattr("turnstile_service.jobs.get_backend", lambda: _Paid())
    res = _submit(live_client, [_doc_example()])
    assert res.status_code == 202
    final = _poll_to_done(live_client, res.json()["job_id"])
    assert final["status"] == "error"
    assert "MockBackend" in final["error"]
    assert isinstance(get_backend(), MockBackend)  # global untouched


def test_run_experiment_job_parallel_matches_sequential():
    """Day-3 Track C: run_experiment_job(max_workers=4) MUST equal the
    default sequential result byte-for-byte (ordered assembly by corpus
    index, single aggregate_experiment reduce). A jitter backend scrambles
    completion order to prove assembly is order-independent."""
    import hashlib
    import time

    from turnstile_replay import reset_backend, set_backend

    calls = []
    for i in range(8):
        dup = copy.deepcopy(_doc_example())
        dup["id"] = f"job-par-{i}"
        calls.append(dup)
    rates, _ = _engine()
    priced = _price_calls(calls, rates)
    variant = VariantSpec.model_validate(_route_variant())

    def _jitter(context, original_span, variant):
        slot = int(hashlib.sha256(
            context.conversation_id.encode("utf-8")).hexdigest(), 16) % 5
        time.sleep(0.002 * (slot + 1))
        return MockBackend()(context, original_span, variant)

    class _JitterBackend(MockBackend):
        """MockBackend with a trace-dependent sleep: still a MockBackend for
        the job's $0 guard, but completion order scrambles under the pool."""

        def __call__(self, context, original_span, variant):
            _jitter(context, original_span, variant)
            return super().__call__(context, original_span, variant)

    set_backend(_JitterBackend())
    try:
        sequential = run_experiment_job(priced, variant)  # default: workers=1
        parallel = run_experiment_job(priced, variant, max_workers=4)
    finally:
        reset_backend()

    assert parallel["n_calls"] == sequential["n_calls"] == 8
    # Map width is observability, not an aggregate: if the payload reports
    # it, it MUST equal the requested width on each side; everything else --
    # trials, Wilson CI, gate verdict -- MUST be byte-identical.
    seq_w = sequential.pop("workers", None)
    par_w = parallel.pop("workers", None)
    if seq_w is not None or par_w is not None:
        assert (seq_w, par_w) == (1, 4)
    seq_json = json.dumps(sequential, sort_keys=True, separators=(",", ":"))
    par_json = json.dumps(parallel, sort_keys=True, separators=(",", ":"))
    assert par_json == seq_json  # byte-identical: trials, Wilson CI, gate
