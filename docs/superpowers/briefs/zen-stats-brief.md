# Zen agent brief — `packages/stats/`

Paste into OpenCode (Zen). Pure, well-specified statistics with a hard test oracle — a cheap model (DeepSeek V4 Flash) is ideal here because correctness is verifiable against known reference values. Independent of the replay engine (which is built separately); this module only consumes `Trial` results and produces an `ExperimentResult`.

---

**MISSION:** Implement the statistics for the experiment layer — the numbers a skeptical CTO will challenge: a Wilson score interval on outcome preservation, and a bootstrap 95% CI on Δcost, plus the aggregation of replay trials into an `ExperimentResult`.

**PACKAGE:** `packages/stats/` — a new proper uv workspace member (mirror `packages/verdict/pyproject.toml`: hatchling, `src/turnstile_stats`, depends on `turnstile-schema` via `{workspace = true}`; add a `conftest.py` putting `src/` on the path like the sibling packages). You may add **numpy** as a dependency (pre-authorized — it's the point). No other deps without asking. Edit nothing outside `packages/stats/`.

**CONTRACTS (from `turnstile_schema`, do not change):**
- `Trial` = `{trace_id: str, status: str ("ok"|"divergent"|"excluded"), delta_cost: float|None, delta_latency_ms: float|None, outcome_preserved: bool|None}`
- `ExperimentResult` = `{n: int, outcome_preservation_rate: float, delta_cost_mean: float, delta_cost_ci95: tuple[float,float], delta_latency_p50: float, delta_latency_p95: float, divergent_exemplars: list[str]}`

**FUNCTIONS TO IMPLEMENT** (`src/turnstile_stats/`):

```python
def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. n==0 -> (0.0, 0.0)."""

def bootstrap_ci(values: list[float], *, n_resamples: int = 10000,
                 ci: float = 0.95, seed: int = 12345) -> tuple[float, float]:
    """Percentile bootstrap CI for the MEAN of `values`. Deterministic given `seed`
    (use numpy.random.default_rng(seed)). Empty -> (0.0, 0.0)."""

def aggregate_experiment(trials: list[Trial]) -> ExperimentResult:
    """Aggregate replay trials into an ExperimentResult.
    - n = number of NON-excluded trials (status != 'excluded').
    - outcome_preservation_rate = mean of outcome_preserved over trials where it is not None
      (report alongside its Wilson interval via wilson_interval — store the rate; the CI is
      computed by callers/tests from the same counts).
    - delta_cost_mean / delta_cost_ci95 = mean and bootstrap_ci over non-None delta_cost of
      NON-excluded, NON-divergent trials.
    - delta_latency_p50 / p95 = 50th/95th percentile of non-None delta_latency_ms (same subset).
    - divergent_exemplars = trace_ids of trials with status == 'divergent'.
    Document precisely which trials feed which statistic."""
```

**Formulas (implement exactly):**
- Wilson: `p=k/n`, `denom=1+z^2/n`, `center=(p + z^2/(2n))/denom`, `margin=(z/denom)*sqrt(p(1-p)/n + z^2/(4n^2))`, interval `(center-margin, center+margin)`, clamped to [0,1].
- Bootstrap: resample `values` with replacement `n_resamples` times (numpy rng with `seed`), take the mean of each resample, return the 2.5th and 97.5th percentiles (for ci=0.95).

**ACCEPTANCE (this is the oracle — a cheap model is fine because these are checkable):**
- `wilson_interval` unit tests against **known reference values**: e.g. `wilson_interval(96,100)` ≈ (0.9007, 0.9840) to 3 decimals; `wilson_interval(50,100)` ≈ (0.4038, 0.5962); `wilson_interval(0,0) == (0.0, 0.0)`; monotonic (more successes → higher center).
- `bootstrap_ci` is **deterministic** with the default seed (same input → same output across runs — assert it); the CI brackets the sample mean; on a large normal-ish sample the 95% CI half-width is small and symmetric-ish; empty → (0,0).
- `aggregate_experiment` tests: excluded trials don't count toward `n`; divergent trace_ids land in `divergent_exemplars` and are excluded from Δcost stats; preservation rate = correct fraction; p50/p95 correct on a known latency list; a hand-built list of `Trial`s produces the expected `ExperimentResult`.
- `uv run pytest packages/stats -q` green; `uv run pytest packages/schema -q` still green (workspace intact).

**FORBIDDEN:** editing `packages/schema/`, `packages/replay/` (built separately), or any other package; changing the `ExperimentResult`/`Trial` contracts; hand-rolling RNG in a non-deterministic way; using a non-seeded global random.

**WHEN STUCK:** stop and report; do not approximate a formula — these numbers get challenged in the room.
