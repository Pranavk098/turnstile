# Turnstile Wave 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the frozen foundation — a validated trace schema, 20 hand-authored golden fixtures, a dated rate table, a `contract-test` CI gate, and a proven `audio.playback` capture path — so that Wave 1's parallel agents can develop against fixtures without waiting on the live voice agent.

**Architecture:** A `uv`-managed Python monorepo. `packages/schema/` defines the canonical `Trace` type and every span model as Pydantic v2 classes whose fields carry OTel/GenAI dotted-key aliases, so on-disk fixtures use real OTel attribute names (`gen_ai.system`, `turnstile.*`) while code uses snake_case. The 20 fixtures are serialized `Trace` objects. `contract-test` = `pytest` that validates every fixture against the schema and enforces the required fixture distribution. A separate WSL2 probe proves the local TTS sink reports played-vs-synthesized characters (the Detector-7 kill-check).

**Tech Stack:** Python 3.12 · uv (workspace) · Pydantic v2 · PyYAML · pytest · Piper TTS (WSL2, kill-check only) · Make (CI/WSL) with a native-Windows `uv run` equivalent.

**Spec:** `docs/superpowers/specs/2026-08-30-turnstile-design.md` (which layers on the frozen contracts in `turnstile-prd.md` §3/§4/§5).

## Global Constraints

- **Frozen contracts:** `turnstile-prd.md` §3 (schema), §4 (cost model), §5 (interfaces) are binding. Field names, formulas, and signatures come from there verbatim. Do not add, rename, or drop a required attribute.
- **Ownership:** Only the human + this session author `packages/schema/` and `fixtures/golden/`. No other agent edits them.
- **No invented constants:** Every rate/threshold lives in config with a dated source-URL comment. Never hardcode a rate into logic.
- **On-disk fixtures use OTel dotted keys** (`gen_ai.system`, `turnstile.audio_seconds`, …), not snake_case. Models parse them via Pydantic aliases with `populate_by_name=True`.
- **Strictness:** All models except `VadSegment` use `extra="forbid"` — an unknown attribute is a schema violation. `VadSegment` uses `extra="allow"` because the PRD does not freeze VAD attributes.
- **Schema version:** `turnstile.schema_version = "1.0"`.
- **Canonical test command:** `uv run pytest packages/schema -q` (native Windows). `make contract-test` calls the same thing (WSL2/CI).
- **Every task ends green** — no task is "done" without its tests passing and a commit.

---

## File Structure

```
turnstile/
├── pyproject.toml                                    # uv workspace root + dev deps (pytest)
├── Makefile                                          # contract-test target
├── .gitignore
├── pricing/
│   └── rates.yaml                                    # dated, sourced rates (local-priced-as + OpenAI)
├── fixtures/golden/
│   ├── manifest.yaml                                 # the 20 required fixtures + category + target detector
│   ├── 00_baseline_clean.json ... 19_edge_40_turn.json
│   └── _builder.py                                   # authoring helper (valid-by-construction)
└── packages/schema/
    ├── pyproject.toml                                # pydantic, pyyaml
    ├── src/turnstile_schema/
    │   ├── __init__.py                               # public exports
    │   ├── enums.py                                  # all Literal/Enum types
    │   ├── spans.py                                  # Span + all span models
    │   ├── trace.py                                  # Conversation, Turn, Trace, load_trace
    │   └── rates.py                                  # RateTable models + load_rates
    └── tests/
        ├── test_enums.py
        ├── test_spans.py
        ├── test_trace.py
        ├── test_rates.py
        └── test_fixtures.py                          # contract-test: validates all fixtures + distribution
```

**Responsibilities:** `enums.py` = closed vocabularies. `spans.py` = one class per span type, each owning its frozen attributes. `trace.py` = the nesting (`Trace → Conversation + [Turn] + TelephonyLeg`) and the loader. `rates.py` = the priced-rate contract type. `test_fixtures.py` = the gate that makes parallel development safe.

---

## Task 1: Repo scaffold + CI harness

**Files:**
- Create: `pyproject.toml`, `packages/schema/pyproject.toml`, `packages/schema/src/turnstile_schema/__init__.py`, `Makefile`, `.gitignore`
- Test: `packages/schema/tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `turnstile_schema` package; `uv run pytest packages/schema -q` runs; `make contract-test` target exists.

- [ ] **Step 1: Write the failing smoke test**

```python
# packages/schema/tests/test_smoke.py
import turnstile_schema

def test_package_imports_and_declares_version():
    assert turnstile_schema.SCHEMA_VERSION == "1.0"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/schema/tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: turnstile_schema` (package not yet installed).

- [ ] **Step 3: Create the root workspace `pyproject.toml`**

```toml
[project]
name = "turnstile"
version = "0.0.0"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = []
addopts = "-q"
```

- [ ] **Step 4: Create `packages/schema/pyproject.toml`**

```toml
[project]
name = "turnstile-schema"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.6", "pyyaml>=6.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/turnstile_schema"]
```

- [ ] **Step 5: Create the package entry point**

```python
# packages/schema/src/turnstile_schema/__init__.py
SCHEMA_VERSION = "1.0"
```

- [ ] **Step 6: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
.uv/
.pytest_cache/
*.wav
corpus/
experiments/*.json
```

- [ ] **Step 7: Create the `Makefile`**

```makefile
.PHONY: contract-test
contract-test:
	uv run pytest packages/schema -q
```

- [ ] **Step 8: Sync and run the smoke test**

Run: `uv sync && uv run pytest packages/schema/tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml Makefile .gitignore packages/schema
git commit -m "chore: scaffold uv workspace + schema package + contract-test harness"
```

---

## Task 2: Enums, Conversation, and Turn

**Files:**
- Create: `packages/schema/src/turnstile_schema/enums.py`
- Create: `packages/schema/src/turnstile_schema/trace.py` (partial — Conversation, Turn)
- Test: `packages/schema/tests/test_enums.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EndReason`, `SpeakerFirst`, `PruningStrategy`, `DecisionKind`, `ToolKind`, `Direction`, `VerdictLabel` (str enums); `Conversation`, `Turn` (Pydantic models). `Turn` fields: `turn_index:int, speaker_first:SpeakerFirst, wall_start_ms:int, wall_end_ms:int, barge_in:bool`, plus child-span lists `vad, asr, tools, llm, tts, playback` and optional `context`. (Span types arrive in Tasks 3–5; use forward refs / `model_rebuild()` in Task 6.)

- [ ] **Step 1: Write the failing test**

```python
# packages/schema/tests/test_enums.py
import pytest
from pydantic import ValidationError
from turnstile_schema.enums import EndReason, DecisionKind
from turnstile_schema.trace import Conversation

def test_end_reason_vocabulary():
    assert set(e.value for e in EndReason) == {
        "caller_hangup", "agent_hangup", "escalated", "timeout", "error"}

def test_conversation_rejects_unknown_end_reason():
    with pytest.raises(ValidationError):
        Conversation(
            conversation_id="c1", agent_version="v1", scenario_id="s1",
            started_at="2026-08-30T00:00:00Z", ended_at="2026-08-30T00:01:00Z",
            end_reason="exploded")

def test_conversation_defaults_schema_version():
    c = Conversation(
        conversation_id="c1", agent_version="v1", scenario_id="s1",
        started_at="2026-08-30T00:00:00Z", ended_at="2026-08-30T00:01:00Z",
        end_reason="caller_hangup")
    assert c.schema_version == "1.0"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest packages/schema/tests/test_enums.py -v`
Expected: FAIL — `ModuleNotFoundError: turnstile_schema.enums`.

- [ ] **Step 3: Write `enums.py`**

```python
# packages/schema/src/turnstile_schema/enums.py
from enum import Enum

class EndReason(str, Enum):
    caller_hangup = "caller_hangup"
    agent_hangup = "agent_hangup"
    escalated = "escalated"
    timeout = "timeout"
    error = "error"

class SpeakerFirst(str, Enum):
    caller = "caller"
    agent = "agent"

class PruningStrategy(str, Enum):
    none = "none"
    window = "window"
    summarize = "summarize"
    semantic = "semantic"

class DecisionKind(str, Enum):
    route = "route"
    slot_fill = "slot_fill"
    tool_select = "tool_select"
    compose = "compose"
    escalate_check = "escalate_check"

class ToolKind(str, Enum):
    retrieval = "retrieval"
    mutation = "mutation"
    lookup = "lookup"
    handoff = "handoff"

class Direction(str, Enum):
    inbound = "inbound"
    outbound = "outbound"

class VerdictLabel(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"
    MISROUTED = "MISROUTED"
    FALSE_RESOLVE = "FALSE_RESOLVE"
```

- [ ] **Step 4: Write the `Conversation` and `Turn` models in `trace.py`**

```python
# packages/schema/src/turnstile_schema/trace.py
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from turnstile_schema.enums import EndReason, SpeakerFirst
from turnstile_schema.spans import (
    VadSegment, AsrTranscribe, ContextAssemble, LlmDecide,
    ToolCall, TtsSynthesize, AudioPlayback,
)

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")

class Conversation(BaseModel):
    model_config = _STRICT
    conversation_id: str
    agent_version: str
    scenario_id: str
    started_at: datetime
    ended_at: datetime
    end_reason: EndReason
    schema_version: str = Field("1.0", alias="turnstile.schema_version")

class Turn(BaseModel):
    model_config = _STRICT
    turn_index: int
    speaker_first: SpeakerFirst
    wall_start_ms: int
    wall_end_ms: int
    barge_in: bool = False
    vad: list[VadSegment] = Field(default_factory=list)
    asr: list[AsrTranscribe] = Field(default_factory=list)
    context: ContextAssemble | None = None
    llm: list[LlmDecide] = Field(default_factory=list)
    tools: list[ToolCall] = Field(default_factory=list)
    tts: list[TtsSynthesize] = Field(default_factory=list)
    playback: list[AudioPlayback] = Field(default_factory=list)
```

Note: `trace.py` imports from `spans.py`, which is written in Tasks 3–5. Until then the import fails — that is expected; this task's test only exercises `Conversation`, but the import chain needs `spans.py`. To keep this task independently green, create a **temporary stub** `spans.py` exporting empty classes, then replace it in Tasks 3–5:

```python
# packages/schema/src/turnstile_schema/spans.py  (TEMPORARY STUB — replaced in Tasks 3-5)
from pydantic import BaseModel
class VadSegment(BaseModel): ...
class AsrTranscribe(BaseModel): ...
class ContextAssemble(BaseModel): ...
class LlmDecide(BaseModel): ...
class ToolCall(BaseModel): ...
class TtsSynthesize(BaseModel): ...
class AudioPlayback(BaseModel): ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/schema/tests/test_enums.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/schema/src/turnstile_schema/enums.py packages/schema/src/turnstile_schema/trace.py packages/schema/src/turnstile_schema/spans.py packages/schema/tests/test_enums.py
git commit -m "feat(schema): enums, Conversation, Turn + temp span stubs"
```

---

## Task 3: Leaf spans — ASR, context.assemble, VAD

**Files:**
- Modify: `packages/schema/src/turnstile_schema/spans.py` (replace stub — add base `Span`, `VadSegment`, `AsrTranscribe`, `ContextAssemble`)
- Test: `packages/schema/tests/test_spans.py`

**Interfaces:**
- Consumes: `enums.PruningStrategy`.
- Produces: `Span` (base, has `span_id:str`), `VadSegment` (`extra="allow"`), `AsrTranscribe`, `ContextAssemble`. All parse OTel dotted keys via alias.

- [ ] **Step 1: Write the failing test**

```python
# packages/schema/tests/test_spans.py
import pytest
from pydantic import ValidationError
from turnstile_schema.spans import AsrTranscribe, ContextAssemble, VadSegment

def test_asr_parses_otel_dotted_keys():
    span = AsrTranscribe.model_validate({
        "span_id": "s1",
        "gen_ai.system": "deepgram",
        "gen_ai.request.model": "nova-3",
        "turnstile.audio_seconds": 4.82,
        "turnstile.is_streaming": True,
        "turnstile.transcript": "hello",
        "turnstile.confidence": 0.94,
    })
    assert span.audio_seconds == 4.82
    assert span.gen_ai_system == "deepgram"

def test_asr_forbids_unknown_attribute():
    with pytest.raises(ValidationError):
        AsrTranscribe.model_validate({
            "span_id": "s1", "gen_ai.system": "deepgram",
            "gen_ai.request.model": "nova-3", "turnstile.audio_seconds": 1.0,
            "turnstile.is_streaming": True, "turnstile.transcript": "x",
            "turnstile.confidence": 0.9, "turnstile.bogus": 1})

def test_vad_allows_extra_because_uncontracted():
    v = VadSegment.model_validate({"span_id": "s1", "turnstile.anything": 5})
    assert v.span_id == "s1"

def test_context_assemble_parses():
    c = ContextAssemble.model_validate({
        "span_id": "s1", "turnstile.context_tokens": 3840,
        "turnstile.history_tokens": 2900, "turnstile.system_tokens": 620,
        "turnstile.retrieved_tokens": 320, "turnstile.retrieved_doc_ids": ["kb_412"],
        "turnstile.pruning_strategy": "none"})
    assert c.context_tokens == 3840
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest packages/schema/tests/test_spans.py -v`
Expected: FAIL — stub classes lack these fields / aliases.

- [ ] **Step 3: Replace `spans.py` with the base + leaf spans**

```python
# packages/schema/src/turnstile_schema/spans.py
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from turnstile_schema.enums import PruningStrategy

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")

class Span(BaseModel):
    model_config = _STRICT
    span_id: str

class VadSegment(Span):
    # PRD does not freeze VAD attributes; allow extra so we do not invent contract.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

class AsrTranscribe(Span):
    gen_ai_system: str = Field(alias="gen_ai.system")
    gen_ai_request_model: str = Field(alias="gen_ai.request.model")
    audio_seconds: float = Field(alias="turnstile.audio_seconds")
    is_streaming: bool = Field(alias="turnstile.is_streaming")
    transcript: str = Field(alias="turnstile.transcript")
    confidence: float = Field(alias="turnstile.confidence")

class ContextAssemble(Span):
    context_tokens: int = Field(alias="turnstile.context_tokens")
    history_tokens: int = Field(alias="turnstile.history_tokens")
    system_tokens: int = Field(alias="turnstile.system_tokens")
    retrieved_tokens: int = Field(alias="turnstile.retrieved_tokens")
    retrieved_doc_ids: list[str] = Field(alias="turnstile.retrieved_doc_ids")
    pruning_strategy: PruningStrategy = Field(alias="turnstile.pruning_strategy")

# Placeholders kept so trace.py imports still resolve until Tasks 4-5 replace them.
class LlmDecide(Span): ...
class ToolCall(Span): ...
class TtsSynthesize(Span): ...
class AudioPlayback(Span): ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/schema/tests/test_spans.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/schema/src/turnstile_schema/spans.py packages/schema/tests/test_spans.py
git commit -m "feat(schema): base Span + asr/context/vad leaf spans with OTel aliases"
```

---

## Task 4: `llm.decide` and `tool.call`

**Files:**
- Modify: `packages/schema/src/turnstile_schema/spans.py` (replace the `LlmDecide` and `ToolCall` placeholders)
- Test: `packages/schema/tests/test_spans.py` (add cases)

**Interfaces:**
- Consumes: `enums.DecisionKind`, `enums.ToolKind`.
- Produces: `LlmDecide` (all PRD §3.2 fields; `cache_read_tokens`/`cache_write_tokens`/`reasoning_tokens` default 0; `retry_of` defaults None), `ToolCall` (`cost_usd` defaults 0.0).

- [ ] **Step 1: Add failing tests**

```python
# append to packages/schema/tests/test_spans.py
from turnstile_schema.spans import LlmDecide, ToolCall

def test_llm_decide_full_parse_and_defaults():
    s = LlmDecide.model_validate({
        "span_id": "s1", "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-5",
        "gen_ai.usage.input_tokens": 3840, "gen_ai.usage.output_tokens": 28,
        "turnstile.decision_kind": "route", "turnstile.decision_chosen": "lookup_order",
        "turnstile.decision_candidates": ["lookup_order", "escalate"],
        "turnstile.output_text": "ok", "turnstile.latency_ms": 820})
    assert s.decision_kind.value == "route"
    assert s.cache_read_tokens == 0 and s.reasoning_tokens == 0
    assert s.retry_of is None

def test_llm_decide_requires_decision_kind():
    with pytest.raises(ValidationError):
        LlmDecide.model_validate({
            "span_id": "s1", "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 5,
            "turnstile.decision_chosen": "x", "turnstile.decision_candidates": ["x"],
            "turnstile.output_text": "x", "turnstile.latency_ms": 1})

def test_tool_call_parse_and_default_cost():
    t = ToolCall.model_validate({
        "span_id": "s1", "turnstile.tool_name": "lookup_order",
        "turnstile.args_hash": "sha256:aa", "turnstile.args_json": "{}",
        "turnstile.result_hash": "sha256:bb", "turnstile.latency_ms": 340,
        "turnstile.tool_kind": "lookup"})
    assert t.cost_usd == 0.0 and t.tool_kind.value == "lookup"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/schema/tests/test_spans.py -v`
Expected: FAIL — placeholders lack fields.

- [ ] **Step 3: Replace the `LlmDecide`/`ToolCall` placeholders**

```python
# in packages/schema/src/turnstile_schema/spans.py — replace the two placeholder classes
from turnstile_schema.enums import DecisionKind, ToolKind  # add to imports at top

class LlmDecide(Span):
    gen_ai_system: str = Field(alias="gen_ai.system")
    gen_ai_request_model: str = Field(alias="gen_ai.request.model")
    input_tokens: int = Field(alias="gen_ai.usage.input_tokens")
    output_tokens: int = Field(alias="gen_ai.usage.output_tokens")
    cache_read_tokens: int = Field(0, alias="turnstile.cache_read_tokens")
    cache_write_tokens: int = Field(0, alias="turnstile.cache_write_tokens")
    reasoning_tokens: int = Field(0, alias="turnstile.reasoning_tokens")
    decision_kind: DecisionKind = Field(alias="turnstile.decision_kind")
    decision_chosen: str = Field(alias="turnstile.decision_chosen")
    decision_candidates: list[str] = Field(alias="turnstile.decision_candidates")
    output_text: str = Field(alias="turnstile.output_text")
    latency_ms: int = Field(alias="turnstile.latency_ms")
    retry_of: str | None = Field(None, alias="turnstile.retry_of")

class ToolCall(Span):
    tool_name: str = Field(alias="turnstile.tool_name")
    args_hash: str = Field(alias="turnstile.args_hash")
    args_json: str = Field(alias="turnstile.args_json")
    result_hash: str = Field(alias="turnstile.result_hash")
    latency_ms: int = Field(alias="turnstile.latency_ms")
    cost_usd: float = Field(0.0, alias="turnstile.cost_usd")
    tool_kind: ToolKind = Field(alias="turnstile.tool_kind")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/schema/tests/test_spans.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add packages/schema/src/turnstile_schema/spans.py packages/schema/tests/test_spans.py
git commit -m "feat(schema): llm.decide + tool.call spans"
```

---

## Task 5: `tts.synthesize`, `audio.playback`, `telephony.leg`

**Files:**
- Modify: `packages/schema/src/turnstile_schema/spans.py` (replace `TtsSynthesize`, `AudioPlayback` placeholders; add `TelephonyLeg`)
- Test: `packages/schema/tests/test_spans.py` (add cases)

**Interfaces:**
- Consumes: `enums.Direction`.
- Produces: `TtsSynthesize`, `AudioPlayback` (`truncated_by` is `"barge_in" | "hangup" | None`, default None), `TelephonyLeg`.

- [ ] **Step 1: Add failing tests**

```python
# append to packages/schema/tests/test_spans.py
from turnstile_schema.spans import TtsSynthesize, AudioPlayback, TelephonyLeg

def test_tts_and_playback_gap_is_representable():
    tts = TtsSynthesize.model_validate({
        "span_id": "t1", "gen_ai.system": "piper",
        "turnstile.chars_synthesized": 184,
        "turnstile.audio_seconds_generated": 11.2, "turnstile.text": "hi"})
    pb = AudioPlayback.model_validate({
        "span_id": "p1", "turnstile.chars_played": 61,
        "turnstile.audio_seconds_played": 3.8, "turnstile.truncated_by": "barge_in"})
    assert tts.chars_synthesized > pb.chars_played          # Detector 7 precondition
    assert pb.truncated_by == "barge_in"

def test_playback_truncated_by_defaults_none():
    pb = AudioPlayback.model_validate({
        "span_id": "p1", "turnstile.chars_played": 61,
        "turnstile.audio_seconds_played": 3.8})
    assert pb.truncated_by is None

def test_telephony_leg_parse():
    leg = TelephonyLeg.model_validate({
        "span_id": "leg1", "turnstile.provider": "twilio",
        "turnstile.direction": "inbound", "turnstile.billable_seconds": 184})
    assert leg.billable_seconds == 184
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/schema/tests/test_spans.py -v`
Expected: FAIL.

- [ ] **Step 3: Replace placeholders + add `TelephonyLeg`**

```python
# in spans.py — replace the two placeholders and append TelephonyLeg
from typing import Literal            # add to imports
from turnstile_schema.enums import Direction   # add to imports

class TtsSynthesize(Span):
    gen_ai_system: str = Field(alias="gen_ai.system")
    chars_synthesized: int = Field(alias="turnstile.chars_synthesized")
    audio_seconds_generated: float = Field(alias="turnstile.audio_seconds_generated")
    text: str = Field(alias="turnstile.text")

class AudioPlayback(Span):
    chars_played: int = Field(alias="turnstile.chars_played")
    audio_seconds_played: float = Field(alias="turnstile.audio_seconds_played")
    truncated_by: Literal["barge_in", "hangup"] | None = Field(
        None, alias="turnstile.truncated_by")

class TelephonyLeg(Span):
    provider: str = Field(alias="turnstile.provider")
    direction: Direction = Field(alias="turnstile.direction")
    billable_seconds: int = Field(alias="turnstile.billable_seconds")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/schema/tests/test_spans.py -v`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit**

```bash
git add packages/schema/src/turnstile_schema/spans.py packages/schema/tests/test_spans.py
git commit -m "feat(schema): tts/playback/telephony spans"
```

---

## Task 6: Assemble `Trace` + `load_trace`

**Files:**
- Modify: `packages/schema/src/turnstile_schema/trace.py` (add `Trace`, `load_trace`, `model_rebuild`)
- Modify: `packages/schema/src/turnstile_schema/__init__.py` (export public API)
- Test: `packages/schema/tests/test_trace.py`

**Interfaces:**
- Consumes: `Conversation`, `Turn`, all span models, `TelephonyLeg`.
- Produces: `Trace` (`conversation:Conversation`, `turns:list[Turn]`, `telephony:TelephonyLeg|None`) and `load_trace(path)->Trace`. Public exports: every model + `load_trace` + `SCHEMA_VERSION`.

- [ ] **Step 1: Write the failing test**

```python
# packages/schema/tests/test_trace.py
import json, pytest
from pydantic import ValidationError
from turnstile_schema import Trace, load_trace

MINIMAL = {
    "conversation": {
        "conversation_id": "c1", "agent_version": "v1", "scenario_id": "order_status",
        "started_at": "2026-08-30T00:00:00Z", "ended_at": "2026-08-30T00:00:30Z",
        "end_reason": "caller_hangup"},
    "turns": [{
        "turn_index": 0, "speaker_first": "caller",
        "wall_start_ms": 0, "wall_end_ms": 3000,
        "llm": [{
            "span_id": "l0", "gen_ai.system": "openai", "gen_ai.request.model": "gpt-5",
            "gen_ai.usage.input_tokens": 500, "gen_ai.usage.output_tokens": 20,
            "turnstile.decision_kind": "compose", "turnstile.decision_chosen": "greet",
            "turnstile.decision_candidates": ["greet"], "turnstile.output_text": "hello",
            "turnstile.latency_ms": 300}]}],
    "telephony": {
        "span_id": "leg1", "turnstile.provider": "twilio",
        "turnstile.direction": "inbound", "turnstile.billable_seconds": 30},
}

def test_trace_round_trips():
    t = Trace.model_validate(MINIMAL)
    assert t.turns[0].llm[0].decision_kind.value == "compose"
    assert t.telephony.billable_seconds == 30

def test_trace_rejects_unknown_top_level_key():
    bad = dict(MINIMAL, surprise=1)
    with pytest.raises(ValidationError):
        Trace.model_validate(bad)

def test_load_trace_from_disk(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(MINIMAL))
    assert load_trace(p).conversation.scenario_id == "order_status"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/schema/tests/test_trace.py -v`
Expected: FAIL — `Trace` / `load_trace` not exported.

- [ ] **Step 3: Add `Trace` + loader to `trace.py`**

```python
# append to packages/schema/src/turnstile_schema/trace.py
import json
from pathlib import Path
from turnstile_schema.spans import TelephonyLeg

class Trace(BaseModel):
    model_config = _STRICT
    conversation: Conversation
    turns: list[Turn]
    telephony: TelephonyLeg | None = None

def load_trace(path: str | Path) -> Trace:
    return Trace.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
```

- [ ] **Step 4: Export the public API**

```python
# packages/schema/src/turnstile_schema/__init__.py
SCHEMA_VERSION = "1.0"

from turnstile_schema.enums import (
    EndReason, SpeakerFirst, PruningStrategy, DecisionKind, ToolKind,
    Direction, VerdictLabel,
)
from turnstile_schema.spans import (
    Span, VadSegment, AsrTranscribe, ContextAssemble, LlmDecide, ToolCall,
    TtsSynthesize, AudioPlayback, TelephonyLeg,
)
from turnstile_schema.trace import Conversation, Turn, Trace, load_trace

__all__ = [
    "SCHEMA_VERSION", "EndReason", "SpeakerFirst", "PruningStrategy",
    "DecisionKind", "ToolKind", "Direction", "VerdictLabel", "Span",
    "VadSegment", "AsrTranscribe", "ContextAssemble", "LlmDecide", "ToolCall",
    "TtsSynthesize", "AudioPlayback", "TelephonyLeg", "Conversation", "Turn",
    "Trace", "load_trace",
]
```

- [ ] **Step 5: Run the full schema suite**

Run: `uv run pytest packages/schema -q`
Expected: PASS (all tests to date).

- [ ] **Step 6: Commit**

```bash
git add packages/schema/src/turnstile_schema/trace.py packages/schema/src/turnstile_schema/__init__.py packages/schema/tests/test_trace.py
git commit -m "feat(schema): Trace assembly + load_trace + public API"
```

---

## Task 7: `RateTable` contract + `pricing/rates.yaml`

**Files:**
- Create: `packages/schema/src/turnstile_schema/rates.py`
- Create: `pricing/rates.yaml`
- Modify: `packages/schema/src/turnstile_schema/__init__.py` (export `RateTable`, `load_rates`)
- Test: `packages/schema/tests/test_rates.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RateTable` (`asr/llm/tts/telephony` dicts of typed rate models) and `load_rates(path)->RateTable`. `LlmRate` fields: `unit, input, output, cache_read=0.0, cache_write=0.0`. This is the `RateTable` type referenced by PRD §5 `price_trace(trace, rates: RateTable)`.

- [ ] **Step 1: Write the failing test**

```python
# packages/schema/tests/test_rates.py
from pathlib import Path
from turnstile_schema import load_rates

RATES = Path(__file__).parents[3] / "pricing" / "rates.yaml"

def test_rates_file_loads_and_types():
    rt = load_rates(RATES)
    assert "openai/gpt-5" in rt.llm
    gpt5 = rt.llm["openai/gpt-5"]
    assert gpt5.input == 1.25 and gpt5.output == 10.00
    assert rt.llm["openai/gpt-5-nano"].input == 0.05

def test_rates_have_expected_sections():
    rt = load_rates(RATES)
    assert rt.asr and rt.tts and rt.telephony and rt.llm
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/schema/tests/test_rates.py -v`
Expected: FAIL — `load_rates` not exported / file missing.

- [ ] **Step 3: Write `rates.py`**

```python
# packages/schema/src/turnstile_schema/rates.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict

_STRICT = ConfigDict(extra="forbid")

class AsrRate(BaseModel):
    model_config = _STRICT
    unit: Literal["audio_minute"]
    rate: float

class LlmRate(BaseModel):
    model_config = _STRICT
    unit: Literal["mtok"]
    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0

class TtsRate(BaseModel):
    model_config = _STRICT
    unit: Literal["char_1k"]
    rate: float

class TelephonyRate(BaseModel):
    model_config = _STRICT
    unit: Literal["minute"]
    rate: float

class RateTable(BaseModel):
    model_config = _STRICT
    asr: dict[str, AsrRate]
    llm: dict[str, LlmRate]
    tts: dict[str, TtsRate]
    telephony: dict[str, TelephonyRate]

def load_rates(path: str | Path) -> RateTable:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RateTable.model_validate(data)
```

- [ ] **Step 4: Write `pricing/rates.yaml`** (every entry dated + sourced; local providers priced-as, OpenAI real)

```yaml
# Turnstile rate table — every rate dated with a source URL. Never hardcode a rate into logic.
# Local audio providers are "priced-as" the named cloud vendor (Path B, spec §2 D2).
asr:
  deepgram/nova-3:            # https://deepgram.com/pricing  (retrieved 2026-08-30)
    { unit: audio_minute, rate: 0.0043 }
llm:
  openai/gpt-5:               # https://openai.com/api/pricing  (retrieved 2026-08-30)
    { unit: mtok, input: 1.25, cache_read: 0.125, cache_write: 0.0, output: 10.00 }
  openai/gpt-5-mini:          # https://openai.com/api/pricing  (retrieved 2026-08-30)
    { unit: mtok, input: 0.25, cache_read: 0.025, cache_write: 0.0, output: 2.00 }
  openai/gpt-5-nano:          # https://openai.com/api/pricing  (retrieved 2026-08-30)
    { unit: mtok, input: 0.05, cache_read: 0.005, cache_write: 0.0, output: 0.40 }
tts:
  cartesia/sonic-2:           # https://cartesia.ai/pricing  (retrieved 2026-08-30)
    { unit: char_1k, rate: 0.025 }
telephony:
  twilio/pstn_inbound:        # https://www.twilio.com/en-us/voice/pricing  (retrieved 2026-08-30)
    { unit: minute, rate: 0.0085 }
```

> Note: `cache_read`/`cache_write` for OpenAI are placeholders to confirm against the live pricing page during execution; the `input`/`output` values above match the researched Aug-2026 rates. Update the dated comment if you re-pull.

- [ ] **Step 5: Export and run**

Add to `__init__.py` imports/`__all__`: `from turnstile_schema.rates import RateTable, load_rates` and add `"RateTable", "load_rates"` to `__all__`.

Run: `uv run pytest packages/schema/tests/test_rates.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/schema/src/turnstile_schema/rates.py pricing/rates.yaml packages/schema/src/turnstile_schema/__init__.py packages/schema/tests/test_rates.py
git commit -m "feat(schema): RateTable contract + dated rates.yaml (OpenAI + local-priced-as)"
```

---

## Task 8: Fixture builder + the `contract-test` gate (with fixtures 00 and 07 authored)

**Files:**
- Create: `fixtures/golden/_builder.py`
- Create: `fixtures/golden/manifest.yaml`
- Create: `fixtures/golden/00_baseline_clean.json`, `fixtures/golden/07_barge_in_waste.json`
- Test: `packages/schema/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `turnstile_schema.load_trace`.
- Produces: `manifest.yaml` (list of 20 `{id, category, target_detector, description}`); a `contract-test` that (a) validates every `fixtures/golden/*.json` against `Trace`, (b) asserts the manifest category distribution, (c) asserts each listed fixture file exists.

- [ ] **Step 1: Write the failing contract-test**

```python
# packages/schema/tests/test_fixtures.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/schema/tests/test_fixtures.py -v`
Expected: FAIL — manifest + fixtures missing.

- [ ] **Step 3: Write the fixture builder helper** (makes hand-authoring valid-by-construction)

```python
# fixtures/golden/_builder.py
"""Ergonomic, valid-by-construction builders for golden fixtures.
Run a builder function and json.dump its .model_dump(by_alias=True) to disk."""
from __future__ import annotations
from turnstile_schema import (
    Trace, Conversation, Turn, LlmDecide, ToolCall, TtsSynthesize,
    AudioPlayback, AsrTranscribe, ContextAssemble, TelephonyLeg,
)

def conv(cid, scenario, end_reason, start="2026-08-30T00:00:00Z",
         end="2026-08-30T00:02:00Z", agent_version="agent@abc123"):
    return Conversation(conversation_id=cid, agent_version=agent_version,
                        scenario_id=scenario, started_at=start, ended_at=end,
                        end_reason=end_reason)

def llm(span_id, model, kind, chosen, candidates, out_text,
        in_tok, out_tok, latency=500, cache_read=0, system="openai"):
    return LlmDecide.model_validate({
        "span_id": span_id, "gen_ai.system": system, "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": in_tok, "gen_ai.usage.output_tokens": out_tok,
        "turnstile.cache_read_tokens": cache_read, "turnstile.decision_kind": kind,
        "turnstile.decision_chosen": chosen, "turnstile.decision_candidates": candidates,
        "turnstile.output_text": out_text, "turnstile.latency_ms": latency})

def tts(span_id, text, chars, secs, system="piper"):
    return TtsSynthesize.model_validate({
        "span_id": span_id, "gen_ai.system": system,
        "turnstile.chars_synthesized": chars,
        "turnstile.audio_seconds_generated": secs, "turnstile.text": text})

def playback(span_id, chars, secs, truncated_by=None):
    d = {"span_id": span_id, "turnstile.chars_played": chars,
         "turnstile.audio_seconds_played": secs}
    if truncated_by:
        d["turnstile.truncated_by"] = truncated_by
    return AudioPlayback.model_validate(d)

def tool(span_id, name, args_hash, kind, result_hash="sha256:r", latency=300):
    return ToolCall.model_validate({
        "span_id": span_id, "turnstile.tool_name": name,
        "turnstile.args_hash": args_hash, "turnstile.args_json": "{}",
        "turnstile.result_hash": result_hash, "turnstile.latency_ms": latency,
        "turnstile.tool_kind": kind})

def leg(billable_seconds, provider="twilio", direction="inbound"):
    return TelephonyLeg.model_validate({
        "span_id": "leg", "turnstile.provider": provider,
        "turnstile.direction": direction,
        "turnstile.billable_seconds": billable_seconds})

def dump(trace: Trace, path):
    import json
    path.write_text(json.dumps(trace.model_dump(by_alias=True, mode="json"),
                               indent=2), encoding="utf-8")
```

- [ ] **Step 4: Write `manifest.yaml`** (the 20-fixture contract — see the trigger table in Task 9)

```yaml
# The 20 golden fixtures. category drives the contract-test distribution check.
fixtures:
  - { id: "00_baseline_clean",    category: baseline,     target_detector: none, description: "Clean RESOLVED order-status call; all detectors silent." }
  - { id: "01_over_model",        category: detector,     target_detector: 1,    description: "Frontier gpt-5 used for a route decision, output_tokens<32." }
  - { id: "02_context_bloat",     category: detector,     target_detector: 2,    description: "input_tokens grow >400/turn, cache_read/input<0.5." }
  - { id: "03_redundant_retrieval", category: detector,   target_detector: 3,    description: "retrieval tool returns a doc already in prior context." }
  - { id: "04_turn_inflation",    category: detector,     target_detector: 4,    description: "14 turns for an intent whose baseline p50 is 8." }
  - { id: "05_reprompt_loop",     category: detector,     target_detector: 5,    description: "Same slot_fill decision_kind twice, no fill between." }
  - { id: "06_dead_tokens",       category: detector,     target_detector: 6,    description: "llm output_text with no matching tts.synthesize." }
  - { id: "07_barge_in_waste",    category: detector,     target_detector: 7,    description: "chars_synthesized > chars_played; caller interrupted." }
  - { id: "08_silence_tax",       category: detector,     target_detector: 8,    description: "Inter-span gaps >200ms with meter running." }
  - { id: "09_escalation_debt",   category: detector,     target_detector: 9,    description: "Escalated; predictable at turn 3, ran 9 more turns." }
  - { id: "10_tool_thrash",       category: detector,     target_detector: 10,   description: "Duplicate args_hash for same tool within conversation." }
  - { id: "11_multi_waste_a",     category: multi_waste,  target_detector: "1,2,8", description: "over_model + context_bloat + silence_tax." }
  - { id: "12_multi_waste_b",     category: multi_waste,  target_detector: "6,7,10", description: "dead_tokens + barge_in + tool_thrash." }
  - { id: "13_multi_waste_c",     category: multi_waste,  target_detector: "3,4,5", description: "redundant_retrieval + turn_inflation + reprompt_loop." }
  - { id: "14_escalation_early",  category: escalation,   target_detector: 9,    description: "Escalated; turn_of_no_return at turn 3." }
  - { id: "15_escalation_late",   category: escalation,   target_detector: 9,    description: "Escalated near end; low escalation debt (control)." }
  - { id: "16_abandoned",         category: abandoned,    target_detector: none, description: "caller_hangup mid-flow; verdict ABANDONED." }
  - { id: "17_false_resolve",     category: false_resolve, target_detector: none, description: "Agent asserts done; terminal mutation tool contradicts." }
  - { id: "18_edge_single_turn",  category: edge,         target_detector: none, description: "Single-turn RESOLVED call." }
  - { id: "19_edge_40_turn",      category: edge,         target_detector: none, description: "40-turn call; scaling/perf edge." }
```

- [ ] **Step 5: Author fixture `00_baseline_clean.json`** (worked example — a clean, cheap, resolved call; every detector must stay silent on it)

Create a small script `fixtures/golden/_author_00_07.py` that builds and dumps them, then run it. The baseline: 3 turns, cheap `gpt-5-mini` decisions, TTS fully played (chars_played == chars_synthesized), no gaps, no barge-in, RESOLVED via a successful mutation tool.

```python
# fixtures/golden/_author_00_07.py  (run once to emit the two JSON files)
from pathlib import Path
from _builder import conv, llm, tts, playback, tool, leg, dump
from turnstile_schema import Trace, Turn

HERE = Path(__file__).parent

# ---- 00 baseline: clean, resolved, no waste ----
t0 = Turn(turn_index=0, speaker_first="caller", wall_start_ms=0, wall_end_ms=4000,
          llm=[llm("l0", "openai/gpt-5-mini", "route", "order_status",
                   ["order_status", "billing"], "Let me check that.", 600, 12)],
          tts=[tts("t0", "Let me check that.", 18, 1.4)],
          playback=[playback("p0", 18, 1.4)])                      # fully played
t1 = Turn(turn_index=1, speaker_first="agent", wall_start_ms=4000, wall_end_ms=8000,
          tools=[tool("tool1", "lookup_order", "sha256:a1", "lookup")],
          llm=[llm("l1", "openai/gpt-5-mini", "compose", "report_status",
                   ["report_status"], "Your order ships tomorrow.", 900, 20)],
          tts=[tts("t1", "Your order ships tomorrow.", 26, 2.0)],
          playback=[playback("p1", 26, 2.0)])
t2 = Turn(turn_index=2, speaker_first="caller", wall_start_ms=8000, wall_end_ms=10000,
          llm=[llm("l2", "openai/gpt-5-mini", "compose", "farewell",
                   ["farewell"], "Anything else? Goodbye.", 700, 10)],
          tts=[tts("t2", "Anything else? Goodbye.", 23, 1.6)],
          playback=[playback("p2", 23, 1.6)])
dump(Trace(conversation=conv("00000000-0000-0000-0000-000000000000",
           "order_status", "caller_hangup"), turns=[t0, t1, t2],
           telephony=leg(10)), HERE / "00_baseline_clean.json")

# ---- 07 barge-in waste: synthesized >> played, caller interrupted ----
b0 = Turn(turn_index=0, speaker_first="agent", wall_start_ms=0, wall_end_ms=6000,
          barge_in=True,
          llm=[llm("l0", "openai/gpt-5", "compose", "long_explanation",
                   ["long_explanation"],
                   "Here is a very long explanation of our refund policy ...",
                   1200, 140)],
          tts=[tts("t0", "Here is a very long explanation of our refund policy "
                         "that continues well past where the caller interrupts.",
                   184, 11.2)],
          playback=[playback("p0", 61, 3.8, truncated_by="barge_in")])  # 123 chars billed, unheard
dump(Trace(conversation=conv("00000000-0000-0000-0000-000000000007",
           "refund", "caller_hangup"), turns=[b0], telephony=leg(6)),
     HERE / "07_barge_in_waste.json")
print("wrote 00 and 07")
```

Run: `cd fixtures/golden && uv run python _author_00_07.py && cd ../..`
Expected: prints `wrote 00 and 07`; two JSON files appear.

- [ ] **Step 6: Run the contract-test** (distribution will still fail — only 2 of 20 fixtures exist; the two that exist must validate)

Run: `uv run pytest packages/schema/tests/test_fixtures.py -v`
Expected: `test_fixture_is_schema_valid[00_baseline_clean.json]` and `[07_barge_in_waste.json]` PASS; `test_every_manifest_fixture_file_exists` FAILs (18 missing). This is the correct red state that Task 9 turns green.

- [ ] **Step 7: Commit**

```bash
git add fixtures/golden packages/schema/tests/test_fixtures.py
git commit -m "feat(fixtures): builder, manifest, contract-test gate + fixtures 00 and 07"
```

---

## Task 9: Author the remaining 18 golden fixtures

**Files:**
- Create: `fixtures/golden/01_over_model.json` … `19_edge_40_turn.json` (18 files)

**Interfaces:**
- Consumes: `fixtures/golden/_builder.py`.
- Produces: 18 schema-valid traces that turn `test_fixtures.py` fully green. Each must satisfy the exact trigger condition below (these are the detector preconditions from PRD §6 / verdict labels from §7) **and** be otherwise realistic.

**Trigger spec — each fixture must encode exactly this precondition:**

| id | Must contain (precondition the detector keys on) |
|----|--------------------------------------------------|
| 01_over_model | An `llm.decide` with `decision_kind` ∈ {route, slot_fill, escalate_check}, `output_tokens < 32`, `model = openai/gpt-5` (frontier tier). |
| 02_context_bloat | ≥5 turns where `input_tokens` rises >400/turn (e.g. 800→1300→1900→2600→3400) and every `cache_read_tokens` is 0 (ratio <0.5). |
| 03_redundant_retrieval | A `tool.call` with `tool_kind=retrieval` returning a doc id that also appears in an earlier turn's `context.assemble.retrieved_doc_ids`. |
| 04_turn_inflation | 14 turns, all `scenario_id=order_status` (whose baseline p50=8), ending RESOLVED. |
| 05_reprompt_loop | Two `llm.decide` spans with `decision_kind=slot_fill`, same `decision_chosen` slot, in consecutive turns, with no successful fill (no differing tool result) between. |
| 06_dead_tokens | An `llm.decide` whose `output_text` has **no** `tts.synthesize` in the same turn (agent generated text never spoken). |
| 08_silence_tax | Turn wall spans with ≥200ms gaps between child-span end and next start and no `audio.playback` covering the gap (encode via `wall_start_ms`/`wall_end_ms` vs span latencies). |
| 09_escalation_debt | `end_reason=escalated`; an early turn (turn 3) whose state already implies escalation, then 9 more turns before the `handoff` tool. |
| 10_tool_thrash | Two `tool.call` spans, same `tool_name`, **identical** `args_hash`, in the same conversation. |
| 11_multi_waste_a | Combine the 01 + 02 + 08 preconditions in one call. |
| 12_multi_waste_b | Combine the 06 + 07 + 10 preconditions in one call. |
| 13_multi_waste_c | Combine the 03 + 04 + 05 preconditions in one call. |
| 14_escalation_early | `end_reason=escalated`; `handoff` tool at the final turn; escalation implied at turn 3 (mirrors 09 but shorter — turn_of_no_return=3). |
| 15_escalation_late | `end_reason=escalated`; escalation only becomes implied at the penultimate turn (control: low escalation debt). |
| 16_abandoned | `end_reason=caller_hangup` partway through an unfinished slot-fill; no farewell; no terminal tool success. |
| 17_false_resolve | Agent `output_text` asserts completion ("Your refund is processed") but the `tool.call` for the refund `mutation` has a `result_hash` indicating failure/rollback (distinct from the success hash used in 00). |
| 18_edge_single_turn | Exactly one turn; RESOLVED; minimal spans. |
| 19_edge_40_turn | 40 turns, RESOLVED, no waste (scaling edge — loop the baseline turn pattern with incrementing ids and wall times). |

- [ ] **Step 1: Author fixtures 01–10** using `_builder.py` (extend the authoring script or add per-fixture scripts). After writing each file, validate it in isolation.

Run per file, e.g.: `uv run pytest "packages/schema/tests/test_fixtures.py::test_fixture_is_schema_valid[01_over_model.json]" -v`
Expected: PASS for each authored file.

- [ ] **Step 2: Author fixtures 11–19** (multi-waste, escalation, abandoned, false-resolve, edges) the same way.

- [ ] **Step 3: Run the full contract-test**

Run: `make contract-test` (WSL2/CI) or `uv run pytest packages/schema -q` (native Windows)
Expected: **all green** — 20/20 fixtures validate, distribution matches, all manifest files exist.

- [ ] **Step 4: Sanity-check the baseline stays clean**

Manually confirm `00_baseline_clean.json` contains **no** trigger from the table (no barge-in, no duplicate args_hash, no gaps, cache-friendly). This is the false-positive guard every Wave-1 detector will test against.

- [ ] **Step 5: Commit**

```bash
git add fixtures/golden
git commit -m "feat(fixtures): author remaining 18 golden fixtures; contract-test fully green"
```

---

## Task 10: `audio.playback` kill-check probe (Wave 0 DoD #5)

**Files:**
- Create: `packages/agent/spikes/playback_probe.py`
- Create: `packages/agent/spikes/README.md`

**Interfaces:**
- Consumes: a local TTS engine (Piper) + an audio sink, in WSL2.
- Produces: evidence that the sink reports **both** `chars_synthesized` and `chars_played` under an interrupt, so Detector 7 is buildable. Acceptance is a printed report, not a unit test.

**Context:** This is the one hard-gate risk from the spec (§11 DoD #5, §12). Run it in **WSL2**. If it cannot report played-vs-synthesized under interruption, **STOP** and escalate to the human to re-plan the audio layer before Wave 1 spawns — do not work around it.

- [ ] **Step 1: In WSL2, install Piper + deps**

```bash
# WSL2 (Ubuntu). Piper is a small local neural TTS.
python3 -m venv ~/.turnstile-probe && source ~/.turnstile-probe/bin/activate
pip install piper-tts sounddevice numpy
# download a voice model per piper docs (e.g. en_US-lessac-medium)
```

- [ ] **Step 2: Write the probe**

```python
# packages/agent/spikes/playback_probe.py
"""Detector-7 kill-check: prove the local TTS sink reports
chars_synthesized vs chars_played when playback is interrupted.

Synthesize a long utterance, start streaming it to the sink, then simulate a
barge-in by stopping playback partway. Report both character counts.
Exit 0 only if chars_played < chars_synthesized under interruption.
"""
import sys, time, wave, threading

TEXT = ("Here is a very long explanation of our refund policy that continues "
        "well past the point where a caller would normally interrupt to ask a "
        "question, which is exactly the waste Detector 7 measures.")

def synthesize(text: str) -> tuple[bytes, int, float]:
    """Return (pcm_bytes, sample_rate, seconds). Piper writes a WAV we read back."""
    import subprocess, io, os
    wav_path = "/tmp/probe.wav"
    subprocess.run(["piper", "--model", os.environ["PIPER_MODEL"],
                    "--output_file", wav_path], input=text.encode(), check=True)
    with wave.open(wav_path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        pcm = w.readframes(n)
    return pcm, sr, n / sr

def main():
    import sounddevice as sd, numpy as np
    pcm, sr, secs = synthesize(TEXT)
    chars_synth = len(TEXT)
    audio = np.frombuffer(pcm, dtype=np.int16)

    # Map characters to audio position linearly (chars_played ~ played_fraction).
    interrupt_after = secs * 0.33          # barge-in at 1/3
    played = {"frac": 0.0}

    def play():
        sd.play(audio, sr); 
        start = time.time()
        while sd.get_stream().active:
            played["frac"] = min(1.0, (time.time() - start) / secs)
            if time.time() - start >= interrupt_after:
                sd.stop(); break
            time.sleep(0.01)

    play()
    chars_played = int(chars_synth * played["frac"])
    print(f"chars_synthesized = {chars_synth}")
    print(f"chars_played      = {chars_played}")
    print(f"unheard (billed)  = {chars_synth - chars_played}")
    ok = chars_played < chars_synth
    print("KILL-CHECK:", "PASS — playback is measurable" if ok else "FAIL — re-plan audio layer")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the probe**

Run (WSL2): `PIPER_MODEL=/path/to/en_US-lessac-medium.onnx python packages/agent/spikes/playback_probe.py`
Expected: prints three counts with `chars_played < chars_synthesized` and `KILL-CHECK: PASS`.

- [ ] **Step 4: Record the result in `spikes/README.md`**

Write one paragraph: the command, the observed numbers, and the verdict. If PASS, note "Detector 7 is buildable on Path B; playback is captured by mapping stop-time to character position." If FAIL, write "STOP — audio layer re-plan required" and escalate to the human.

- [ ] **Step 5: Commit**

```bash
git add packages/agent/spikes
git commit -m "spike: audio.playback kill-check probe (Detector 7 gate) — PASS"
```

---

## Wave 0 exit gate

Wave 0 is done — and Wave 1 may spawn — only when all are true (spec §11):

- [ ] `uv run pytest packages/schema -q` is fully green.
- [ ] `make contract-test` passes: 20/20 fixtures schema-valid, distribution matches, all manifest files present.
- [ ] `pricing/rates.yaml` has dated, sourced rates incl. `openai/gpt-5`, `gpt-5-mini`, `gpt-5-nano`.
- [ ] The `audio.playback` probe printed `KILL-CHECK: PASS` (or the human has re-planned the audio layer).
- [ ] Spec + schema + fixtures committed to git.

On green: proceed to Wave 1 (spec §10) — spawn the Zen mechanical lane (`pricing/`, detectors 2/6/7/8/10, `dashboard/`) and this session's judgment lane (`agent/`+`otel/`, `verdict/`), all developing against `fixtures/golden/`.

---

## Self-Review

**Spec coverage:** schema (§5 → Tasks 2–6), rates.yaml incl. OpenAI (§5, §2.1 → Task 7), 20 fixtures with required distribution (§5.1 → Tasks 8–9), contract-test CI (§9,§10 → Tasks 1,8), audio.playback kill-check (§11 DoD#5, §12 → Task 10), ownership/no-invented-constants (Global Constraints). Verdict labels type is defined in Task 2 (`VerdictLabel`) so the Wave-1 verdict agent consumes a frozen enum. **Gap check:** VAD is intentionally under-constrained (documented). No other spec item is unmapped for Wave 0. `caller/`, `replay/`, detectors, dashboard are Wave 1/2 — out of this plan's scope by design.

**Placeholder scan:** No "TBD/TODO/handle edge cases" in code steps. The one "placeholder" note (OpenAI cache rates in rates.yaml) is an explicit verify-against-live instruction with concrete current values present, not a blank.

**Type consistency:** `load_trace`, `load_rates`, `RateTable`, `LlmRate.input/output/cache_read`, `Trace{conversation,turns,telephony}`, `Turn{llm,tools,tts,playback,context,asr,vad}`, span alias names — all consistent across Tasks 2–9 and the builder in Task 8. Builder function names (`conv/llm/tts/playback/tool/leg/dump`) are used consistently in Tasks 8–9.
