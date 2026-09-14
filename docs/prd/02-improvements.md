# PRD 02 — improvements delegation brief

**Executor:** OpenCode · **Reviewer:** Claude · **Scope:** three small follow-ups to
the Vapi ingest adapter. No detector/verdict-layer changes.

## Global constraints (unchanged from PRD 02)

- **$0.** Pure data transformation + docs; no provider/model API call anywhere.
- **Honesty labels load-bearing.** No invented fields; loud `IngestError` over silent
  guessing; the §5 `decision_kind` boundary stays exactly as built.
- **No frozen-contract edits**; native path stays byte-identical (the pinned
  `test_native_provenance_strings_unchanged_without_provider` must stay green).
- `uv run pytest` green, no regression.

---

## Task 1 — ship commented-out telephony rate rows + a pointer in the error

**Why:** outbound or non-Twilio legs fail loudly today because the rate key isn't in
`pricing/rates.yaml`. That's the correct behavior, but it's friction for a real user
trying their own Vapi export. Give them an uncomment-and-go template.

**Do:**
1. In `pricing/rates.yaml`, add **commented-out** telephony rows for the common Vapi
   legs (outbound PSTN, and at least one non-Twilio provider Vapi supports). Each row
   must follow the repo convention: **a dated source-URL comment** for the rate. They
   stay commented so logic is unchanged; they are a template the user uncomments.
2. Improve the `IngestError` raised on an unresolvable telephony rate key so it names
   the missing key **and** points at the commented template ("add a rate row for
   `<key>`; see the commented examples in `pricing/rates.yaml`").

**Acceptance:**
- Rates file parses; the commented rows are syntactically valid once uncommented
  (a test that uncomments them in a temp copy and loads them, or a documented manual
  check).
- The improved error message names the key and the template; a test asserts it.
- No change to any priced number (rows are commented) — native + Vapi sample outputs
  unchanged.

---

## Task 2 — surface the margin-excluded count in the CLI headline

**Why:** when provider-adapted (inferred-`decision_kind`) calls are excluded from the
recoverable-margin replay, the count lives only in provenance. The CLI headline
should say so plainly, since it's a headline-honesty point.

**Do:** in `turnstile_ingest.__main__`, where the headline prints (recoverable margin
+ detectors-with-data), add a line when `n_margin_excluded > 0`, e.g.
`"margin over 6/7 calls — 1 provider-adapted call excluded (inferred decision_kind)"`.
Pull the number from what `run_calls` already computes; do not recompute.

**Acceptance:**
- `uv run python -m turnstile_ingest --provider vapi` prints the excluded-count line.
- Native `--sample` (no exclusions) prints no such line (unchanged output).
- A CLI test asserts both.

---

## Task 3 — document the margin-denominator choice (doc-only, honesty)

**Why:** `run_calls` computes `recoverable_margin_pct` over the **measurable subset**
(inferred calls excluded from both numerator and denominator), not total fleet spend.
This is a deliberate, defensible choice, but it's a headline-number semantics decision
and must be written down where the other honesty boundaries live.

**Do:** add a short paragraph to `docs/METHOD.md` (or `docs/INGEST.md`, wherever the
recoverable-margin definition is closest) stating: the margin denominator is the sum
of measurable calls' cost; provider-adapted calls with inferred `decision_kind` are
excluded from both parts and disclosed in the fleet note; this keeps the % a true
statement about the analyzable spend, never diluted or inflated by calls the tool
cannot yet measure. Link it to LIMITATIONS.md if appropriate. **No code change.**

**Acceptance:** the paragraph exists, is consistent with the code's actual behavior,
and the link-checker (from PRD 06) stays green.

---

## Explicitly out of scope (do NOT build; documented triggers)

- **D9 tier-2 rule for `assistant-forwarded-call` with a failed transfer** — touches
  the verdict/detector layer and can only be designed honestly against real forwarded-
  call exports. Revisit when such exports exist.
- **Retell (or any second provider) adapter** — a new feature, not an improvement.
  The `provider_info` plumbing is already provider-agnostic; validate the Vapi adapter
  on real data before adding a second.

## Handoff

Reviewer will check: rows are commented + dated, the §5 boundary and native byte-
identity are untouched, the CLI line pulls the existing count (no recompute), and the
METHOD note matches actual behavior.
