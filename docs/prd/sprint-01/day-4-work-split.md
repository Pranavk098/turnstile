# Day 4 — Work Split (delegation plan for parallel sessions)

**Inherits `00-charter.md` and `day-4-quality-calibrated.md` in full.** This document
only *decomposes* the day-PRD into delegable parts; it does not loosen any rule. Where
this document is silent, the day-PRD and charter govern.

Each **Part** below is one working session. Parts in the same wave have **disjoint file
ownership** and may run in parallel. Every part MUST be delivered through the charter §3
Recursive Self-Verification Loop (hard cap 6 iterations), with a dynamic-check
transcript attached as evidence. "Unit tests pass" is never done.

---

## 0. Ground truth (verified against the repo — do not re-assume)

These facts were checked against the code on Day-4 morning. Sessions MUST treat them as
the starting state and MUST NOT "rediscover" contradictory assumptions:

1. **The gate exists and is pure logic.** `packages/quality/src/turnstile_quality/calibration.py`:
   `judge_may_score(dim_id)` = paid flag (`TURNSTILE_ALLOW_PAID=1`) AND registered
   `Calibration(n_labels ≥ 60, kappa ≥ 0.75, ece is not None)`. `JUDGE_DIMENSIONS =
   ("faithfulness", "answer_relevance")`. Unknown ids raise `CalibrationError` on
   register and return `False` on query. **No judge implementation exists** — the report
   path always renders the two judge dims as `score=None, label="pending",
   tier="not_measured", method="judge_pending"` (`dimensions.py::_pending_dimension`).
2. **Gate unit tests are already load-bearing** (`packages/quality/tests/test_calibration.py`):
   default-closed, each requirement necessary, unknown-id rejection, and the
   cannot-be-coaxed test. Day-4 MUST keep every one green and ADD the *dynamic* (running
   system) coax evidence the day-PRD requires.
3. **No-network rule inside the package.** `test_no_network_imports_in_quality_package`
   bans `urllib/requests/httpx/openai/socket/http./aiohttp` imports in
   `src/turnstile_quality/*.py`. **Consequence (load-bearing for Part E/F design):** the
   paid reference labeler and any model-calling judge client MUST live outside the
   package (e.g. `scripts/`), with the package exposing only pure schemas/protocols and
   injected callables. Do NOT subvert the test (e.g. via subpackages) — that is a
   charter violation.
4. **Barge-in gap is in the ingest adapter, not the dimension.**
   `_barge_in_courtesy` already scores pass/fail from `playback.truncated_by` vs turn
   `barge_in` (golden fixture `07_barge_in_waste` carries `truncated_by="barge_in"` and
   reads `pass`; agreement tests pin this). The gap:
   `packages/ingest/src/turnstile_ingest/adapter.py` (playback-span block, ~line 173)
   **hardcodes `"turnstile.truncated_by": None`**, so ingest-originated calls (the live
   barge-in loop emits `barge_in=True` + `chars_played < chars_synthesized`) read as
   *talked-over / fail* even when the agent yielded. Schema needs no change:
   `AudioPlayback.truncated_by` (`Literal["barge_in","hangup"] | None`) already exists.
5. **Byte-stability audit for the adapter fix (pre-verified):** golden fixtures are
   v1.1 traces (never pass through the adapter) → untouched. The native 51-call sample
   fleet (`packages/ingest/data/data.json`) has **zero** turns with both `barge_in` and
   playback spans → byte-identical. Day-2 Vapi/Retell calls carry no char counts → no
   playback spans → byte-identical. The fix is therefore byte-safe by construction, but
   the regen-and-diff check in Part C is still MANDATORY (prove it, don't assert it).
6. **Quality is already in the serve path.** `pipeline.py::_run_priced` calls
   `evaluate_quality` per call; the fleet rollup (`_accumulate_quality`) and the
   beside-cost one-liner (`summarize_quality`) exist. The dashboard renders pending dims
   as a literal "calibration pending" badge, never a numeral (`index.html`,
   `qualityTierChip` / rubric renderer; pinned by `test_frontend.py` and
   `test_evaluate.py`). Day-4 MUST NOT regress this rendering.
7. **Latency budget (day-PRD, tightened):** deterministic quality eval MUST add
   **< 20 ms per call** to the existing path. Judge calls (paid, off by default) that
   can exceed 1 s MUST run async (Day-3 jobs), never blocking `/api/evaluate`.
8. **Spends:** the reference-labeler is one of the two permitted spends (charter §1.1):
   opt-in behind `TURNSTILE_ALLOW_PAID`, logged, reproducible, capped, **absent from CI**.
9. **Frozen contracts:** `evaluate_quality(priced, verdict)` signature and the gate's
   public rules MUST NOT change (day-PRD "Interfaces"). Additive-only to the report
   shape. `packages/schema` and pricing formulas are frozen.
10. **Test command:** `uv run pytest` (workspace root). CI on the pushed tip MUST be
    green at end of day (charter §1.5).

---

## 1. Wave plan & dependency graph

```
Wave 1 (4 parallel sessions, disjoint files):
   Part A  labeling tool + label schema + selection manifest
   Part B  κ/ECE statistics + Calibration builder + report writer
   Part C  barge-in courtesy → measured (adapter + live evidence)
   Part D  dynamic coax suite + latency benchmark + UI-pending verification

Wave 2 (1 session + a human rater; needs A's tool and B's builder):
   Part E  reference pre-labeling run (PAID, opt-in) + human labeling/spot-check
           + committed labels + generated calibration report
           ⚠ environmental: needs the paid flag spend and a human rater.
           If 60 labels cannot be produced in budget → honest shortfall report,
           gate stays closed, DO NOT lower the bar (day-PRD §Recursive loop).

Wave 3 (after E; F is conditional):
   Part F  (P1, ONLY IF κ ≥ 0.75) ship judges behind the gate (off by default)
   Part G  (P1) docs surfacing + Day-6 hand-off note

Final (1 session, sequential):
   Part H  integration gate: full suite, byte-diff audit, dynamic transcripts,
           CI green, reviewer checklist
```

**File-ownership matrix (hard boundaries — touching another part's files is a defect):**

| Part | Owns (create/edit) | MUST NOT touch |
|---|---|---|
| A | `packages/quality/src/turnstile_quality/labeling.py` (new), `packages/quality/src/turnstile_quality/__main__.py` (new), `packages/quality/tests/test_labeling.py` (new), `fixtures/calibration/selection.json` (new) | `calibration.py`, `dimensions.py`, `__init__.py`, adapter, service, dashboard |
| B | `packages/quality/src/turnstile_quality/calibration_study.py` (new), `packages/quality/tests/test_calibration_study.py` (new) | `calibration.py`, `dimensions.py`, `__init__.py`, A's files |
| C | `packages/ingest/src/turnstile_ingest/adapter.py` (playback block only), `packages/ingest/tests/` (extend), `packages/live/tests/test_bargein.py` (extend), `docs/INGEST.md` (mapping note) | quality package, service, dashboard, golden fixtures, committed sample data |
| D | `packages/quality/tests/test_gate_dynamic.py` (new), `packages/service/tests/test_quality_gate_wire.py` (new), `scripts/bench_quality.py` (new) | any `src/` file, A/B/C files |
| E | `scripts/reference_label.py` (new), `fixtures/calibration/labels.jsonl`, `fixtures/calibration/reference_log.jsonl`, `fixtures/calibration/spot_checks.jsonl`, `fixtures/calibration/calibration_report.json` (generated) | package `src/` files |
| F | `packages/quality/src/turnstile_quality/judges.py` (new), `packages/quality/src/turnstile_quality/dimensions.py` (dispatch only), `packages/quality/tests/test_judges.py` (new) | `calibration.py` public rules, `evaluate_quality` signature, service `/api/evaluate` blocking path |
| G | `docs/LIMITATIONS.md` (§6 status), `docs/METHOD.md` (quality section), `docs/CALIBRATION.md` (new, or fold into METHOD — pick one, state why) | code |
| H | `packages/quality/src/turnstile_quality/__init__.py` (export wiring only), PR evidence | changing any logic |

**Why `__init__.py` is owned by H:** four parts add modules; letting each edit the
package exports guarantees a 4-way merge conflict. Parts A/B/F import from the full
module path internally; H wires the public exports at integration.

---

## 2. Part A — Labeling tool + label schema + selection manifest (P0 #1, #2-partial)

**Goal.** A pure-stdlib, $0 CLI to hand-label conversations for the two judge
dimensions, plus the committed, deterministic selection of ≥60 conversations to label.

**PRD refs.** Day-4 P0 #1 ("calibration harness + labeling tool (CLI/HTML)"), P0 #2
(first half), strict rule "calibration set + labels MUST be committed (or a reproducible
builder)".

### Steps

1. **Label record schema** (`labeling.py`). One JSONL line per (call, dimension)
   labeling event, pydantic-validated, `extra="forbid"` (match repo style):
   - `call_id: str`, `dim_id: str` (MUST be in `JUDGE_DIMENSIONS` — reject others),
     `reference_label: Literal["pass","fail"] | None`, `reference_confidence: float
     in [0,1] | None`, `human_label: Literal["pass","fail"] | None`,
     `rater: str | None`, `checked_at: iso8601 | None`, `note: str | None`.
   - Rationale (state in docstring): `reference_*` is the pre-label from the paid
     labeler (Part E); `human_*` is the rater's verdict. κ is computed reference-vs-human
     over human-checked rows (Part B). A row with `human_label=None` is *unchecked* and
     MUST NOT count toward n.
2. **Selection manifest** (`fixtures/calibration/selection.json`). Deterministic,
   committed list of ≥60 conversations with `call_id` + source path, drawn ONLY from
   committed data (golden `fixtures/golden/*.json`, native sample
   `packages/ingest/data/data.json`, Day-2 ingested `packages/dashboard/sample/call-ing-*.json`).
   Include a `seed` and a `selection_note` stating the rule (e.g. "all 23 golden + first
   37 native-sample ids, sorted"). The manifest MUST be re-derivable: a `--rebuild` flag
   regenerates identical bytes.
3. **CLI** (`__main__.py`): `uv run python -m turnstile_quality label --selection
   fixtures/calibration/selection.json --labels fixtures/calibration/labels.jsonl
   --rater <name>`.
   - For each unlabeled (call, dim): print the call's transcript (caller/agent text per
     turn, from the source file), print the reference pre-label if one exists, prompt
     `[y] agree / [n] disagree (flip) / [s] skip / [q] quit`.
   - Append-only JSONL writes (never rewrite history); on re-run, resume after the last
     human-checked row. Every written row gets `checked_at` + `rater`.
   - Also a `stats` subcommand printing labeled/total per dimension (no scoring math —
     that is Part B).
4. **Constraints.** No network imports (rule 0.3 — the package test scans top-level
   files). No edits to `calibration.py`/`dimensions.py`. Rendering is terminal text;
   do NOT build the HTML variant (MAY, not MUST — skip it).

### Acceptance (dynamic, transcript required)

- `uv run pytest packages/quality/tests/test_labeling.py` green: schema validation
  (unknown `dim_id` rejected; confidence out of range rejected), JSONL round-trip,
  resume-after-crash, `--rebuild` byte-identical selection.
- **Dynamic:** run the CLI against a 3-call toy selection in a temp dir, drive stdin
  with scripted answers (`y`, `n`, `q`), then read the JSONL back and show the exact
  rows written (capture the terminal transcript).
- `uv run pytest` (full) still green.

---

## 3. Part B — κ/ECE statistics + Calibration builder + report writer (P0 #3)

**Goal.** Pure, known-answer-tested statistics and a builder that turns committed labels
into a `Calibration` + a committed, re-derivable calibration report.

**PRD refs.** Day-4 P0 #3 ("Cohen's κ + ECE computed and committed as a calibration
report (+ confusion matrix)"), strict rule "κ/ECE re-derivable", EARS "WHEN calibration
yields κ < 0.75, the judges SHALL stay pending and the report SHALL state κ/ECE
honestly."

### Steps

1. **`calibration_study.py`** (new; pure stdlib):
   - `cohens_kappa(a: list[str], b: list[str]) -> float` — two-rater, equal-length,
     categorical. Known-answer tests: perfect agreement → 1.0; a published worked
     example (state the source in the test docstring); chance-level → ≈0.
   - `expected_calibration_error(confidences: list[float], correct: list[bool],
     n_bins: int = 10) -> float` — standard equal-width-bin ECE; state the binning in
     the report. Known-answer tests (perfect calibration → 0.0; a hand-computed
     2-bin example).
   - `confusion_matrix(a, b) -> dict` — 2×2 over pass/fail.
   - `build_calibration(dim_id, rows) -> Calibration` — from Part A's label rows:
     uses ONLY rows with `human_label is not None`; `n_labels` = number of such rows;
     κ = reference-vs-human; ECE from `reference_confidence` vs
     `reference_label == human_label`. Import `Calibration` from
     `turnstile_quality.calibration` — do NOT modify that file.
     - **Honesty guard (MUST):** if human-checked rows < 60, or any row lacks
       `reference_confidence`, `build_calibration` MUST NOT fabricate — it returns a
       result marked insufficient (e.g. `None` + the report records the shortfall
       with the actual counts). Never pad, never impute.
   - `write_report(path, per_dim) -> None` — committed JSON artifact
     (`fixtures/calibration/calibration_report.json`) carrying, per dimension:
     `n_labels`, `kappa`, `ece`, `confusion_matrix`, `passes_gate` (n≥60 ∧ κ≥0.75 ∧
     ece present), plus provenance: sha256 of the labels file, tool version string,
     generation timestamp, and the binning rule. Byte-deterministic given the same
     labels (sort keys, fixed float formatting — state it).
   - `load_and_register(report_path) -> None` — reads the committed report and calls
     the existing public `register_calibration(dim_id, Calibration(...))` for each
     dimension. (Runtime wiring that calls this belongs to F/H, not here.)
2. **Tests** (`test_calibration_study.py`): known-answer κ/ECE/matrix; the
   insufficient-data guard (59 rows → no passing Calibration; report states the
   shortfall honestly); determinism (same labels → same report bytes).

### Acceptance (dynamic, transcript required)

- Build a synthetic 60-row labels file by hand script (fixed seed, known agreement
  level), run the builder CLI/API, print the report, and **hand-verify one cell** of
  the confusion matrix and the κ value against an independent computation in the
  transcript.
- Full `uv run pytest` green.

---

## 4. Part C — Barge-in courtesy → measured on real Piper playback (P0 #4)

**Goal.** Close the adapter gap (ground truth 0.4) so ingest-originated barge-in calls
score `barge_in_courtesy` as `measured`, proven on a real-audio call.

**PRD refs.** Day-4 P0 #4; EARS "WHERE playback spans exist, barge-in courtesy SHALL
read measured. *(check: a real-audio call's rendered rubric)*". Roadmap: "wire barge-in
courtesy → measured using the live agent's real Piper playback spans."

### Steps

1. **Adapter fix** (`adapter.py`, playback-span block only). Derive the truncation
   cause from data the ingest call already carries:
   ```python
   truncated = (
       "barge_in"
       if (turn.barge_in
           and tts.chars_played is not None
           and tts.chars_synthesized is not None
           and tts.chars_played < tts.chars_synthesized)
       else None
   )
   ```
   Emit `"turnstile.truncated_by": truncated` on the playback span. Do NOT invent a
   `"hangup"` cause — no ingest field carries it (state this boundary in the code
   comment). Do NOT change span ids, timings, or char counts (D7/D8 read them).
2. **Contract doc** (`docs/INGEST.md`): one additive note in the mapping table — the
   playback span's `turnstile.truncated_by` is `"barge_in"` exactly when the turn is
   flagged `barge_in` and played chars < synthesized chars; otherwise `null`.
3. **Unit tests** (`packages/ingest/tests/`): an ingest call with a barged, cut turn →
   adapted trace has `truncated_by == "barge_in"` on that turn's playback span; a
   non-barged turn → `None`; a barged turn with `chars_played == chars_synthesized`
   (edge) → `None` (nothing was cut — state the rule).
4. **Live-loop agreement test** (`packages/live/tests/test_bargein.py`, extend): run
   `run_bargein_call` with `p_barge=1.0` (test fakes), adapt via
   `turnstile_ingest.adapter.load`, price/adjudicate, then `evaluate_quality` →
   `barge_in_courtesy.tier == "measured"` and `label == "pass"` (every barged turn was
   cut = yielded). Keep determinism (seeded).
5. **Byte-stability proof (MANDATORY):** regenerate the committed ingest artifact
   (`packages/ingest/data/data.json` via its existing builder) and the dashboard sample
   data (`packages/dashboard/build_data.py`), and diff. Expected: byte-identical
   (ground truth 0.5). If ANY byte moves, STOP — that is a defect; report with the diff
   (do not commit moved bytes without a recorded reason tied to P0 #4).

### Acceptance (dynamic, transcript required)

- **Real-audio check:** run one real barge-in call through the live loop with real
  Piper (`uv run python -m turnstile_live --mode bargein --real-audio` with the sweep
  reduced to a single call — use the existing CLI flags; do not add new ones unless
  strictly needed), persist its ingest JSON, boot the service (`uvicorn`), `POST
  /api/evaluate` with that call, and show from the HTTP response:
  `quality.dimensions[id=barge_in_courtesy].tier == "measured"`, label `pass`, and the
  playback `truncated_by` evidence. Attach the curl transcript + the rendered rubric.
- Byte-diff transcript from step 5. Full `uv run pytest` green.

---

## 5. Part D — Dynamic coax suite + latency benchmark + UI-pending verification (P0 gates)

**Goal.** Produce the day-PRD's mandatory *dynamic* evidence that the gate cannot be
illegitimately opened, that the UI never shows a judge numeral, and that the
deterministic quality path stays inside its 20 ms budget.

**PRD refs.** Day-PRD "Recursive loop — Day-4 dynamic checks" (coax through every
illegitimate path: no flag, n<60, κ<0.75, ECE missing, unknown id); EARS #1 (coax test,
run dynamically); latency budget (<20 ms/call); charter §2/§3.

### Steps

1. **`test_gate_dynamic.py`** (quality package): the existing unit coax tests stay;
   ADD the report-path matrix at the `evaluate_quality` level, parametrized over every
   illegitimate path — flag off + valid calibration; flag on + nothing registered;
   flag on + n=59; flag on + κ=0.7499; flag on + ece=None; unknown id (register →
   `CalibrationError`, `judge_may_score` → False). For each: every judge dimension in
   the report has `score is None`, `label == "pending"`, `tier == "not_measured"`,
   `method == "judge_pending"`; `report.overall` computed from deterministic dims only;
   and `summarize_quality(...)` output contains no digit-bearing token for a judge
   dimension. (Registry hygiene: `clear_calibrations()` in fixtures, as the existing
   tests do.)
2. **`test_quality_gate_wire.py`** (service): boot the app (TestClient or uvicorn
   subprocess — match existing service-test style), `POST /api/evaluate` with the
   example call with the paid flag OFF → response `quality` block shows both judge dims
   pending-as-data (`score: null`, `tier: "not_measured"`); the fleet rollup counts
   them as pending, never as pass/fail. Repeat with the flag ON but no calibration
   registered → identical bytes on the judge dims (a score must not appear just because
   the flag is set).
3. **UI verification (dynamic):** serve the dashboard as Day-1 does; fetch the call
   page for a call with a quality block; assert the HTML/JS path renders the literal
   string "calibration pending" for judge dims and that no numeral score is rendered
   for them (follow the existing `test_frontend.py` / DOM-read pattern; if a browser
   harness is unavailable, drive the data + template assertions the existing tests use
   and say so in the transcript).
4. **`scripts/bench_quality.py`:** time `evaluate_quality` over the 23 golden traces
   (N=200 iterations, report median + p95 per call) AND time the full `_run_priced`
   path with and without the quality call to isolate the added ms. Gate: quality slice
   p95 **< 20 ms/call**. Deterministic machine-relative numbers go in the transcript,
   not in any committed doc (PERF.md is Day-3's artifact — do not edit).

### Acceptance (dynamic, transcript required)

- The full coax matrix output (each path → refusal evidence) captured.
- The two service wire tests green; the UI check transcript attached.
- Benchmark output showing p95 < 20 ms/call. Full `uv run pytest` green.

---

## 6. Part E — Reference pre-labeling (PAID, opt-in) + human labeling + committed report (P0 #2, #3)

**Goal.** Produce the committed ≥60-conversation labeled set and the honest calibration
report. **This is the only part that spends money and the only part that needs a human.**

**PRD refs.** Day-4 P0 #2/#3; strict rules: "reference-labeler MAY use the flagged
small paid spend; it MUST be opt-in, logged, reproducible, and absent from CI. Human
spot-checks MUST be recorded." Recursive loop: "If 60 quality labels can't be produced
within budget, that is an **environmental blocker** — ship the harness + report the
shortfall honestly; do NOT lower the bar."

### Steps

1. **`scripts/reference_label.py`** (new — MUST live in `scripts/`, NOT in the package;
   ground truth 0.3). Input: Part A's `selection.json`; output: reference pre-labels
   merged into `fixtures/calibration/labels.jsonl` (as `reference_label` /
   `reference_confidence` rows) plus a spend log
   `fixtures/calibration/reference_log.jsonl`.
   - **Gating (MUST):** refuses to run unless `TURNSTILE_ALLOW_PAID=1` AND an explicit
     `--spend-ack` CLI flag is present. Prints the estimated cost before the first
     paid call and requires the flag.
   - **Reproducibility (MUST):** model id, prompt template hash, and temperature=0 (or
     the provider's deterministic equivalent) pinned as constants in the script and
     echoed into the log. Every paid call logged: call_id, dim_id, tokens, cost_usd,
     running total.
   - **Cap (MUST):** a hard `--max-usd` (default small; state the chosen number and
     why) — the script aborts before exceeding it, keeping every completed label.
   - **CI absence (MUST):** no CI workflow references this script; grep proof in the
     transcript.
   - The labeler emits, per (call, dim): a pass/fail label AND a confidence in [0,1]
     (ECE needs it). Prompt asks for both; parse strictly; a parse failure is logged
     and skipped, never guessed.
2. **Human labeling session.** The rater runs Part A's CLI over all ≥60 selected
   conversations for both dimensions (the pre-labels make this accept/correct-fast).
   Every row ends with a human verdict. **Spot-check record:** afterwards, a second
   pass re-checks a recorded random sample (state the fraction, e.g. 15%, seeded) into
   `fixtures/calibration/spot_checks.jsonl` with per-row agree/disagree + note.
3. **Generate the report:** run Part B's builder over the committed labels →
   `fixtures/calibration/calibration_report.json`. Commit labels + log + spot-checks +
   report together.
4. **Re-derivation proof:** from a clean state, re-run the builder and show the report
   bytes are identical (κ/ECE re-derivable from committed labels — strict rule).
5. **Shortfall branch (only if triggered):** if the cap or time stops labeling before
   60 human-checked rows per dimension, generate the report anyway — it MUST state the
   actual n, the shortfall, and `passes_gate: false`. This is a valid, honest P0
   outcome per the day-PRD; the gate stays closed and Part F is skipped.

### Acceptance (dynamic, transcript required)

- The gating transcript: script refuses without the flag; refuses without
  `--spend-ack`; aborts cleanly at the cap (dry-run with a tiny `--max-usd`).
- The spend log shows every paid call + running total; the total matches the log sum.
- The report's κ/ECE/matrix re-derived byte-identically in the transcript.
- `grep -r "reference_label" .github/` → no hits. Full `uv run pytest` green.

---

## 7. Part F — (P1, CONDITIONAL on κ ≥ 0.75) Ship judges behind the gate

**Precondition (hard):** Part E's report shows `passes_gate: true` for the dimension
being shipped. If κ < 0.75 → **do not start this part**; the report stays the honest
output and judges remain pending (EARS #2). Charter: no P1 while any P0 gate is red.

**Goal.** `faithfulness` / `answer_relevance` emit tiered scores — paid-gated, **off by
default**, never blocking `/api/evaluate`, and surfaced beside cost with the correct
tier.

**PRD refs.** Day-4 P1 #5; EARS #4 ("WHEN κ ≥ 0.75 AND the paid flag is set, a judge
SHALL emit a tiered score that appears beside cost"); latency rule (judge calls async
via Day-3 jobs); Interfaces ("Judges plug in behind `judge_may_score`"; no
`evaluate_quality` signature change; no change to the gate's public rules).

### Steps

1. **`judges.py`** (new, pure): judge *protocol* + prompt builders + strict response
   parsing per dimension (pass/fail + confidence). **No network imports** (ground
   truth 0.3): the model client is an injected callable `(prompt: str) -> str`.
2. **Dispatch** (`dimensions.py`, minimal edit): replace the unconditional
   `_pending_dimension(dim_id)` with: if `judge_may_score(dim_id)` AND a judge callable
   is registered for `dim_id` (a lock-guarded registry mirroring the calibration
   registry — new code, do not edit `calibration.py`'s rules) → score via the callable
   and return the dimension with `method="judge_calibrated"`, `tier="measured"`, and
   `evidence` carrying the calibration provenance (`{n_labels, kappa, ece}`) + the
   judge's confidence. Otherwise → the existing pending no-op, unchanged.
   - `evaluate_quality(priced, verdict)` signature unchanged; a process with no judge
     registered behaves byte-identically to today (default path, flag off).
3. **Wiring (async, off by default):** judge scoring happens in an offline/async flow
   (Day-3 jobs pattern), never inline in `/api/evaluate`. The simplest contract-safe
   shape: a script/flow that (flag on) loads the committed calibration report via
   Part B's `load_and_register`, registers the real client-backed judge, scores the
   selected calls, and commits the judged quality blocks as data the existing surfaces
   render. Any live-endpoint addition is additive-only (charter §4) and async.
4. **Tests** (`test_judges.py`): with flag on + passing calibration + a **fake**
   injected judge → dimension scores with `method="judge_calibrated"` and calibration
   provenance in evidence; flag off OR no calibration OR no judge → pending no-op
   (each path); the default-path report bytes are identical to the pre-F bytes over
   the golden fixtures (byte-diff gate).

### Acceptance (dynamic, transcript required)

- Dynamic eval with a registered passing calibration + fake judge: the score appears in
  the `quality` block AND in the beside-cost line (`summarize_quality`), tiered
  correctly — transcript of the response.
- The same request with the flag off: pending-as-text, bytes unchanged.
- Full coax suite (Part D) still green — the gate's illegitimate paths still refuse.
- Full `uv run pytest` green; no paid call in any test or CI path (grep proof).

---

## 8. Part G — (P1) Docs surfacing + Day-6 hand-off

**Precondition:** Part E's report exists (pass or honest shortfall — either is
documented).

**Goal.** The calibration report (κ/ECE/confusion matrix) is surfaced in the docs with
numbers that match the committed artifact exactly (Day-6 consumes this).

### Steps

1. `docs/LIMITATIONS.md` §6: replace the "pending 60 hand labels + κ ≥ 0.75" status
   line with the outcome — either "calibrated: n=…, κ=…, ECE=… (see
   `fixtures/calibration/calibration_report.json`)" or the honest shortfall statement.
   Numbers MUST be copied from the committed report, never retyped from memory.
2. `docs/METHOD.md` quality section: one additive paragraph on the calibration
   methodology (label source, reference-vs-human κ, ECE binning, spot-check protocol)
   with the same numbers.
3. Hand-off note for Day-6 (in the PR description or `docs/CALIBRATION.md`): what
   changed, where the report lives, what the launch copy may and may not claim
   (a calibrated judge score is still model-graded — surfaces keep
   `method="judge_calibrated"` provenance).

### Acceptance

- `uv run pytest` green (doc-number guards, if any touch these sections, must pass).
- Transcript: `grep` the docs for the κ/ECE strings and show they equal the report's
  values byte-for-byte.

---

## 9. Part H — Final integration gate (sequential, end of day)

**Owner of last resort; runs after A–E (and F/G if attempted).**

1. Wire `packages/quality/src/turnstile_quality/__init__.py` exports for the new
   public names (A's schema, B's builder/report functions, F's registry if shipped) —
   exports only, no logic.
2. Full `uv run pytest` green.
3. Byte-diff audit: committed artifacts (`packages/ingest/data/data.json`,
   `packages/dashboard/sample/*`, golden fixtures) identical to the day-start tip,
   except moves explicitly authorized by P0 #4 (expected: none — ground truth 0.5).
4. Re-run the **entire** Day-4 dynamic set against the running system on the final
   tip: coax matrix (D), real-audio barge-in rubric (C), UI pending/tiered rendering
   (D/F), latency benchmark (D), report re-derivation (E). Attach all transcripts to
   the PR.
5. Push; CI on the tip MUST be green (charter §1.5 — a CI-red day is not done).
6. **Reviewer checklist (Claude checks FIRST — pre-answer each item with evidence):**
   - [ ] No uncalibrated score can reach a headline/beside-cost — proven dynamically
     (D's coax transcripts + F's flag-off bytes, if F shipped).
   - [ ] κ/ECE report committed + honest (E's report + re-derivation transcript).
   - [ ] Barge-in courtesy measured on a real-audio call (C's transcript).
   - [ ] Gate rules unchanged (diff of `calibration.py` shows no rule edits).
   - [ ] $0 default path (no-network test green; paid script gated + absent from CI).
   - [ ] CI green.

---

## 10. P2 (stretch — only after every P0 gate is green AND P1 is done or declined)

- **Active-learning selection:** rank unlabeled committed calls by reference-labeler
  uncertainty (lowest confidence first) as the next labeling batch. Pure function over
  Part E's log; new module, new tests.
- **Second human rater:** a second `labels-rater2.jsonl` via Part A's CLI; inter-rater
  κ (human-vs-human) added to the report via Part B's `cohens_kappa`. Committed like
  everything else.

Both are MAY; neither may start while any P0/P1 gate is red.

---

## 11. Standing rules for every session (repeat of the binding ones)

- RFC-2119 keywords; EARS checks are dynamic, named, and quantified — transcripts or it
  didn't happen.
- Fix root causes; NEVER loosen a threshold, delete a failing check, or subvert the
  no-network test to go green (charter violation).
- Re-run the FULL acceptance set after every fix; regressions are defects.
- Blocked at the 6-iteration cap: STOP, do not ship red; report the blocking defect
  with evidence, distinguishing *environmental* (needs a human/secret/spend) from
  *code* defects.
- The golden fleet headline and all pre-existing committed bytes stay identical unless
  P0 #4 explicitly moves them (expected: nothing moves).
- Additive-only to shared contracts (report shape, `/api/*`, ingest contract, quality
  block, tier vocabulary).
