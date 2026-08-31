# Zen agent brief — `packages/pricing/`

Paste this into OpenCode (Zen) as the agent's mission. It is self-contained. The package develops entirely against the 23 golden fixtures — no live agent, no external calls.

---

**MISSION:** Implement the cost engine: turn a schema-v1.1 `Trace` into a `PricedTrace` by pricing every span against the rate table.

**PACKAGE:** `packages/pricing/` — you may edit nothing outside it. You may *read* `packages/schema/` (the frozen contract), `pricing/rates.yaml`, and `fixtures/golden/*.json`.

**CONTRACT (do not change these signatures):**
```python
from turnstile_schema import Trace, RateTable, PricedTrace, load_trace, load_rates

def price_trace(trace: Trace, rates: RateTable) -> PricedTrace: ...
```
`PricedTrace` (already defined in `turnstile_schema.contracts`) has: `trace: Trace`, `span_costs: dict[str, float]` (span_id → USD), `turn_costs: list[float]` (per turn_index), `conv_cost: float`, `stage_costs: dict` keyed `"asr"|"llm"|"tts"|"telephony"`.

**COST FORMULAS (verbatim from PRD §4.2 — do not alter):**
```
cost_asr = audio_seconds / 60 × rate_per_minute
cost_llm = (input_tokens − cache_read_tokens)/1e6 × rate_in
         + cache_read_tokens/1e6              × rate_cache_read
         + cache_write_tokens/1e6             × rate_cache_write
         + (output_tokens + reasoning_tokens)/1e6 × rate_out
cost_tts = chars_synthesized / 1000 × rate_per_1k        # SYNTHESIZED, never played — the gap is Detector 7
cost_tel = billable_seconds / 60 × rate_per_minute        # attributed to turns pro-rata by each turn's wall time
cost_turn = Σ(child span costs) + attributed telephony
cost_conv = Σ(cost_turn)
```
Telephony attribution: split the leg's total cost across turns proportional to each turn's wall duration `(wall_end_ms − wall_start_ms) / Σ turn wall durations`.

**RATE-KEY RESOLUTION (the convention documented at the top of `pricing/rates.yaml` — use exactly this):**
- `asr` / `llm` span → key = `f"{gen_ai.system}/{gen_ai.request.model}"` (model is the bare name, e.g. `openai/gpt-5-mini`, `deepgram/nova-3`) → look up in `rates.llm` / `rates.asr`.
- `tts` span (no model field) → key = `gen_ai.system` (e.g. `piper`) → look up in `rates.tts`.
- `telephony.leg` → key = `f"{provider}/pstn_{direction}"` (e.g. `twilio/pstn_inbound`) → look up in `rates.telephony`.
Every fixture span is guaranteed to resolve (a schema-package guard test enforces it), so a `KeyError` means your resolution is wrong, not the data.

**INPUTS:** `fixtures/golden/*.json` (load via `load_trace`), `pricing/rates.yaml` (load via `load_rates`).

**OUTPUT:** a `PricedTrace` per the frozen contract, for any of the 23 fixtures.

**ACCEPTANCE (all required):**
- `price_trace` prices all 23 fixtures with no `KeyError` / no missing rate.
- Unit tests cover **every formula branch**: `cost_asr`; `cost_llm` with each of `cache_read>0`, `cache_write>0`, `reasoning>0`, and the plain case; `cost_tts` — assert on a barge-in fixture (07) that cost uses `chars_synthesized`, NOT `chars_played`; `cost_tel` pro-rata split across multiple turns.
- **Decomposition invariants** (assert as tests): `sum(span_costs.values()) + total_telephony == conv_cost`; `sum(stage_costs.values()) == conv_cost`; `sum(turn_costs) == conv_cost` (use `pytest.approx`).
- `make contract-test` (i.e. `uv run pytest packages/schema -q`) still green; `uv run pytest packages/pricing -q` green.

**FORBIDDEN:** editing `packages/schema/`, `fixtures/`, `pricing/rates.yaml`, or any other package; inventing or hardcoding any rate number (all rates come from `rates.yaml`); adding dependencies without asking.

**WHEN STUCK:** stop and report; do not work around the contract or invent a rate.
