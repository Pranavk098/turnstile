# PRD 01 — improvements delegation brief

**Executor:** OpenCode · **Reviewer:** Claude · **Scope:** two small, high-value
follow-ups to the demo eval service. Do **not** touch anything else in
`packages/service`.

## Global constraints (unchanged from PRD 01)

- **$0.** No paid call, key, model client, or outbound HTTP anywhere in the path.
- **Engine purity.** No business math in the service; still exactly one engine call.
- **Stateless.** Uploaded calls processed in-memory, never retained.
- **No frozen-contract edits** (`packages/schema`, pricing formulas).
- `uv run pytest` green, no regression from the current **1008 passed / 4 skipped**.

---

## Task 1 — return per-call detail so a pasted eval can drill down (flame graph)

**Why:** `POST /api/evaluate` currently discards the per-call detail payloads —
`app.py` does `artifact, _details = run_calls(...)` and drops `_details`. Those
payloads already carry `trace`, `span_costs`, `turn_costs`, `verdict`, `findings`,
`_provenance` (see `pipeline._detail_file`) — the exact shape the demo fleet's
per-call files use. So a visitor can paste a call and see fleet-level findings but
cannot open the same flame-graph/detail view the committed demo calls get. Returning
the already-computed details closes that gap for near-zero cost.

**Reviewer sign-off (schema):** approved. The evaluate response becomes the artifact
**plus** an additive top-level `details` key. Nothing existing changes shape.

**Do:**
1. In `app.py::api_evaluate`, stop discarding details. Return
   `content = {**artifact, "details": details}` where `details` is the
   `call-<id>.json -> payload` map `run_calls` already returns. Keep it additive:
   every existing top-level key (`fleet`, `calls`, `findings`, `provenance`, …)
   stays byte-identical.
2. Front-end (`packages/dashboard/index.html`, section 09 evaluate panel): after a
   successful eval, make each returned call row open the **existing** call-detail
   rendering (flame graph + span/turn costs + verdict + findings + provenance),
   fed from `response.details[row.detail]`. Reuse the demo fleet's detail renderer —
   do not author a second one. Keep all pinned front-end strings intact and keep the
   `sample/`-fetch fallback so the file still opens under plain `http.server`.

**Acceptance:**
- `POST /api/evaluate` on the Barge-in preset returns `details` with a `trace` and
  `span_costs` for the call; the panel opens a flame graph matching the demo fleet's
  look for the same call.
- **Parity preserved:** update `test_evaluate_matches_cli_run_calls_exactly` to
  compare the artifact portion (everything except the new `details` key) and assert
  `details` equals the `_details` `run_calls` returns. The artifact portion must
  still equal the CLI byte-for-byte.
- Provenance/honesty labels present in the returned details (extend the existing
  provenance-retention test).
- Still stateless, still `$0`, determinism test still green.

---

## Task 2 — reject oversized bodies before buffering (hardening)

**Why:** `api_evaluate` does `raw = await request.body()` and then checks
`MAX_BODY_BYTES`, so a large body is fully buffered before rejection. The cap
correctly prevents an *engine run* on abusive input, but the docstring's
"DoS-bounded" is stronger than the code.

**Do:** before reading the body, check the `Content-Length` header; if present and
over `MAX_BODY_BYTES`, return the existing 413 immediately without reading the body.
Keep the current post-read length check too (Content-Length can be absent or wrong
under chunked encoding) — defense in depth, same 413 message.

**Acceptance:**
- A request with a `Content-Length` over the cap gets 413 without an engine run
  (add a test asserting the early 413).
- The existing oversized-body and too-many-calls 413 tests still pass.

---

## Explicitly out of scope (do NOT build; documented triggers)

- **Rate limiting / usage counters** — only if the public demo is actually abused.
- **Keep-warm scheduled ping** — only after a real cold-start problem is observed;
  first-paint-from-committed-JSON already covers the common case.
- **Rejoining the `Content-Type` MIME-split literal** — only if the front-end guard
  ever becomes AST-based; it is string-based today, so leave it.

## Handoff

Reviewer will check: additive-only response shape, parity test updated and green,
front-end reuses the existing detail renderer (no second copy, pinned strings
intact), `$0`/stateless invariants, and the early-413 path.
