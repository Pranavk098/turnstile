"""Deterministic outcome-preservation scaffolding (Wave-3 W3-C).

MECHANISM, not a measured number. Outcome-preservation is the one number
Turnstile honestly labels "not measured" (docs/METHOD.md): on the golden
corpus it is vacuous (canned baseline replies always diverge) or structural
(pinned tool effects always preserve). This module removes both INPUT
problems -- real, non-canned probe baselines in fixtures/preservation/ plus
an authored DecisionBackend -- and drives the REAL adjudicate() + REAL
replay() path, proving preservation is now a genuine function of the
replayed decision.

This pass makes NO model call, NO network call, spends NO credit, claims NO
measured preservation number, and changes NO claim in docs/METHOD.md or
docs/LIMITATIONS.md. The honest artifact is "mechanism validated +
non-vacuous on authored cases; the number awaits the owner-gated paid run",
when the real OpenAI backend drops into the same injection slot (the
one-line SWAP POINT in run_preservation below).
"""
from __future__ import annotations

from pathlib import Path

from turnstile_pricing import price_trace
from turnstile_replay import DecisionBackend, get_backend, replay, set_backend
from turnstile_replay.backend import ReplayContext, ReplayedDecision
from turnstile_replay.replay import _similarity
from turnstile_schema import PricedTrace, VariantSpec, load_rates, load_trace
from turnstile_schema.spans import LlmDecide
from turnstile_verdict import adjudicate

ROOT = Path(__file__).resolve().parents[4]
PRESERVATION_FIXTURES_DIR = ROOT / "fixtures" / "preservation"
RATES_PATH = ROOT / "pricing" / "rates.yaml"

# Probe identities (conversation_ids in fixtures/preservation/*.json).
PRESERVE_PROBE_ID = "w3c-preserve-01"
BREAK_PROBE_ID = "w3c-break-01"
DIVERGENT_PROBE_ID = "w3c-divergent-01"

# The cheaper-path model every authored variant reroutes to (a real
# rates.yaml tier, so trials price real rate arbitrage like MockBackend's
# safe reroutes).
CHEAPER_PATH_MODEL = "gpt-5-nano"

# The three contrasting authored variant utterances, keyed by probe:
# preserve keeps a closing keyword (verdict must hold); break drops the
# closing phrase while staying similar (verdict must flip); divergent is an
# unrelated rewrite (trial must be excluded, not counted).
PRESERVE_VARIANT_TEXT = (
    "Your refill for the blue allergy tablets is ready for pickup at the "
    "main counter after two o clock this afternoon - just bring a photo ID "
    "when you come in, and goodbye for now, take care!"
)
BREAK_VARIANT_TEXT = (
    "The downtown branch on Fifth Street is open weekdays from nine in the "
    "morning until six in the evening, and on Saturdays from ten until two "
    "in the afternoon, with the drive-through opening half an hour earlier "
    "every day"
)
DIVERGENT_VARIANT_TEXT = "Hold on a moment while I pull up a different record."

PROBE_VARIANT_TEXTS: dict[str, str] = {
    PRESERVE_PROBE_ID: PRESERVE_VARIANT_TEXT,
    BREAK_PROBE_ID: BREAK_VARIANT_TEXT,
    DIVERGENT_PROBE_ID: DIVERGENT_VARIANT_TEXT,
}

# The variant under test: reroute the verdict-load-bearing slot_fill
# decision to the cheaper path. The authored backend dispatches on probe;
# the real OpenAIBackend later reads this same model_routing slot.
PRESERVATION_VARIANT = VariantSpec(model_routing={"slot_fill": CHEAPER_PATH_MODEL})


class PreservationBackend:
    """Authored DecisionBackend: per probe, the chosen cheaper-path decision.

    Deterministic, fully offline -- no model call, no network. Unknown
    conversation_ids identity-replay (same text, cheaper model id), so the
    harness degrades to a no-op rather than fabricating text.
    """

    def __call__(
        self, context: ReplayContext, original_span: LlmDecide, variant: VariantSpec
    ) -> ReplayedDecision:
        output_text = PROBE_VARIANT_TEXTS.get(
            context.conversation_id, original_span.output_text
        )
        return ReplayedDecision(
            model=CHEAPER_PATH_MODEL,
            output_text=output_text,
            decision_chosen=original_span.decision_chosen,
            input_tokens=original_span.input_tokens,
            output_tokens=original_span.output_tokens,
            cache_read_tokens=original_span.cache_read_tokens,
            cache_write_tokens=original_span.cache_write_tokens,
            reasoning_tokens=original_span.reasoning_tokens,
            latency_ms=original_span.latency_ms,
        )


def load_preservation_corpus(rates=None) -> list[PricedTrace]:
    """Load + price every probe in fixtures/preservation/ (sorted, deterministic)."""
    if rates is None:
        rates = load_rates(RATES_PATH)
    return [
        price_trace(load_trace(path), rates)
        for path in sorted(PRESERVATION_FIXTURES_DIR.glob("*.json"))
    ]


def from_turn_for(priced: PricedTrace) -> int:
    """Replay from the FINAL turn, so replay's pivot (the first replayed
    decision at/after from_turn) IS the verdict-load-bearing final
    utterance -- the span _has_clean_close() reads."""
    return priced.trace.turns[-1].turn_index


def _readjudicated_label(
    priced: PricedTrace, variant_text: str, rates
) -> str:
    """The label replay's rebuilt trace re-adjudicates to (replay's Trial
    carries only the preserved flag, not the label).

    Exact mirror of what replay() adjudicates internally for these probes:
    from_turn is the final turn (a single llm span), tool spans are
    re-served unchanged from the trace cache, and adjudicate() reads only
    decision_kind / output_text / end_reason / tool effects -- all preserved
    except the final output_text. The status/outcome_preserved flags in the
    report still come from replay() itself; this only recovers the label,
    and tests cross-check ((new == original) is outcome_preserved) so any
    drift between this mirror and replay's internals fails loudly.
    """
    final_turn = priced.trace.turns[-1]
    new_llm = [final_turn.llm[0].model_copy(update={"output_text": variant_text})]
    new_trace = priced.trace.model_copy(
        update={
            "turns": [
                *priced.trace.turns[:-1],
                final_turn.model_copy(update={"llm": new_llm}),
            ]
        }
    )
    return adjudicate(price_trace(new_trace, rates)).label.value


def run_preservation(backend: DecisionBackend | None = None) -> dict:
    """Run the real replay path over the probe set under the authored
    backend (default) and aggregate preservation / divergence rates.

    Returns {"n", "n_ok", "n_divergent", "preservation_rate",
    "divergence_rate", "rows"} where each row holds trace_id, from_turn,
    status, original_label, new_label (None when divergent),
    similarity (replay's own _similarity on baseline vs replayed pivot
    text), and outcome_preserved. preservation_rate is the mean of
    outcome_preserved over non-divergent probes (aggregate_experiment's
    rule); divergence_rate is the divergent fraction.
    """
    rates = load_rates(RATES_PATH)
    corpus = load_preservation_corpus(rates)
    active = backend if backend is not None else PreservationBackend()
    # SWAP POINT (owner-gated paid run only -- do NOT enable here):
    # active = OpenAIBackend()  # requires TURNSTILE_ALLOW_PAID=1 + OPENAI_API_KEY
    previous = get_backend()
    set_backend(active)
    try:
        rows = []
        for priced in corpus:
            trace_id = priced.trace.conversation.conversation_id
            original_label = adjudicate(priced).label.value
            from_turn = from_turn_for(priced)
            trial = replay(priced, PRESERVATION_VARIANT, from_turn)
            baseline_text = priced.trace.turns[-1].llm[0].output_text
            variant_text = PROBE_VARIANT_TEXTS.get(trace_id, baseline_text)
            similarity = _similarity(baseline_text, variant_text)
            new_label = (
                None
                if trial.status == "divergent"
                else _readjudicated_label(priced, variant_text, rates)
            )
            rows.append(
                {
                    "trace_id": trace_id,
                    "from_turn": from_turn,
                    "status": trial.status,
                    "original_label": original_label,
                    "new_label": new_label,
                    "similarity": similarity,
                    "outcome_preserved": trial.outcome_preserved,
                }
            )
    finally:
        set_backend(previous)
    preserved = [r for r in rows if r["outcome_preserved"] is not None]
    preservation_rate = (
        sum(r["outcome_preserved"] for r in preserved) / len(preserved)
        if preserved
        else 0.0
    )
    divergence_rate = (
        sum(1 for r in rows if r["status"] == "divergent") / len(rows)
        if rows
        else 0.0
    )
    return {
        "n": len(rows),
        "n_ok": sum(1 for r in rows if r["status"] == "ok"),
        "n_divergent": sum(1 for r in rows if r["status"] == "divergent"),
        "preservation_rate": preservation_rate,
        "divergence_rate": divergence_rate,
        "rows": rows,
    }
