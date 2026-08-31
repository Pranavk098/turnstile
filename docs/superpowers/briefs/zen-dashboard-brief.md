# Zen agent brief — `packages/dashboard/`

Paste into OpenCode (Zen) as the agent's mission. **Run this AFTER the pricing package exists** (the flame graph needs a priced trace). It is presentation-only — it reads JSON and draws; it computes nothing.

---

**MISSION:** Build the static dashboard surface: a **cost flame graph** for one call (the hero), a **fleet view** (CPRC), and a **ranked recoverable-margin** table — reading JSON only, no backend.

**PACKAGE:** `packages/dashboard/` — edit nothing outside it. You may read `packages/schema/`, `packages/pricing/`, and `fixtures/`.

**INPUTS (JSON the page reads — no computation in the page):**
- A **priced-trace sample**: generate it once and commit it under `packages/dashboard/sample/priced_trace.json` by running the pricing package on a fixture, e.g.
  ```python
  from turnstile_schema import load_trace, load_rates
  from turnstile_pricing import price_trace
  pt = price_trace(load_trace("fixtures/golden/00_baseline_clean.json"), load_rates("pricing/rates.yaml"))
  # serialize pt (trace + span_costs + turn_costs + conv_cost + stage_costs) to JSON
  ```
- `fixtures/sample/findings.sample.json` — `list[Finding]` (already exists).
- `fixtures/sample/experiments.sample.json` — `list[ExperimentResult]` (already exists).

**OUTPUT — a static site** (plain HTML+CSS+JS, or Vite/React that `npm run build`s to static assets). Self-contained, runs offline, opens from `file://` or any static host. It renders:
1. **Hero — cost flame graph for one call.** From the priced-trace JSON, a nested/stacked bar: conversation → turns (`turn_costs`) → stages (`stage_costs`: asr/llm/tts/telephony) → spans (`span_costs`). Show the total `conv_cost` and where the money went. This is the demo's opening image ("this call cost $X; here is where it went").
2. **Fleet view.** `CPRC_loaded` vs `CPRC_naive` side by side (use the aggregate numbers from a small provided/derived summary JSON; for the sample, hardcode a plausible summary object in a `sample/fleet.json` you create). Lead with loaded.
3. **Ranked recoverable-margin table.** `findings.sample.json` sorted by `waste_usd` descending: columns class (1–10), turn_index, waste_usd, confidence, and the `proposed_variant`. This is the "ranked interventions in dollars" view.
4. **Replay-evidence panel.** From `experiments.sample.json`: `n`, `outcome_preservation_rate` (+ its Wilson interval if present), `delta_cost_mean` (+ `delta_cost_ci95`), latency deltas, and the count/list of `divergent_exemplars`. This is the "we proved it by replay" panel.

**ACCEPTANCE:**
- Opens and renders all four views from the sample JSON with no backend and no external network calls.
- Flame graph visibly decomposes a real priced trace (not a mock) — the stage costs sum to `conv_cost`.
- If React/Vite: `npm run build` produces a working static bundle. If plain: a single self-contained `index.html` (inline CSS/JS) works from `file://`.
- Committed sample JSONs so the page renders standalone.

**FORBIDDEN:** editing `packages/schema/`, `packages/pricing/`, `fixtures/`, or other packages; requiring a running backend/server; fetching anything over the network; computing costs/metrics in the page (it only presents pre-computed JSON).

**WHEN STUCK:** stop and report. Note: dashboard polish is first on the project cut list — prioritize a working flame graph + ranked table over visual polish.
