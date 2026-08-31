from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from turnstile_schema.enums import VerdictLabel
from turnstile_schema.trace import Trace

_STRICT = ConfigDict(populate_by_name=True, extra="forbid")


class PricedTrace(BaseModel):
    """Output of packages/pricing:price_trace(trace, rates) -> PricedTrace (PRD §4.2/§4.3)."""
    model_config = _STRICT
    trace: Trace
    span_costs: dict[str, float]  # span_id -> cost_usd
    turn_costs: list[float]  # per turn_index
    conv_cost: float
    stage_costs: dict[Literal["asr", "llm", "tts", "telephony"], float]


class VariantSpec(BaseModel):
    """The replay variant space (PRD §8.2). A variant sets only the knobs it changes."""
    model_config = _STRICT
    model_routing: dict[str, str] | None = None
    context_strategy: str | None = None
    prefix_caching: bool | None = None
    retrieval_policy: str | None = None
    tts_chunking: str | None = None
    escalation_policy: str | None = None
    tool_batching: bool | None = None


class Finding(BaseModel):
    """packages/detectors:detect(...) -> list[Finding] (PRD §5/§6). Every finding MUST
    carry a proposed_variant the replay engine can execute."""
    model_config = _STRICT
    class_id: int = Field(ge=1, le=10)
    turn_index: int
    span_id: str
    waste_usd: float
    confidence: float
    proposed_variant: VariantSpec
    evidence: dict


class Verdict(BaseModel):
    """packages/verdict:adjudicate(trace) -> Verdict (PRD §5/§7)."""
    model_config = _STRICT
    label: VerdictLabel
    confidence: float
    evidence: list[dict]
    turn_of_no_return: int | None


class IntentBaseline(BaseModel):
    model_config = _STRICT
    p50_turns: float
    p75_turns: float
    mean_cost_per_turn: float


class Baselines(BaseModel):
    """Per-intent baselines consumed by Detectors 4 and 9."""
    model_config = _STRICT
    per_intent: dict[str, IntentBaseline]


class Trial(BaseModel):
    """packages/replay:replay(trace, variant, from_turn) -> Trial (PRD §8.1)."""
    model_config = _STRICT
    trace_id: str
    status: Literal["ok", "divergent", "excluded"]
    delta_cost: float | None
    delta_latency_ms: float | None
    outcome_preserved: bool | None


class ExperimentResult(BaseModel):
    """packages/replay:experiment(traces, variant) -> ExperimentResult (PRD §5/§8.3)."""
    model_config = _STRICT
    n: int
    outcome_preservation_rate: float
    delta_cost_mean: float
    delta_cost_ci95: tuple[float, float]
    delta_latency_p50: float
    delta_latency_p95: float
    divergent_exemplars: list[str]
