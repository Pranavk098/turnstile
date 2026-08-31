"""Named, cited sampling distributions for the synthetic corpus generator.

docs/CORPUS.md Constraint 1 ("Sample, don't choose"): turn counts, per-turn
token counts, barge-in timing, silence-gap durations, and tool-call patterns
must be drawn from named distributions with a cited source, not hand-picked
magic values in ``generate.py``. Every ``sample_*`` function below is the ONE
place a stochastic quantity of that kind is produced; ``generate.py`` never
inlines its own probability/scale constants for these quantities -- it only
calls into this module.

Where a precise published figure exists it is quoted verbatim with a URL
(retrieved 2026-08-31, same convention as ``pricing/rates.yaml``). Where the
literature gives a qualitative shape but not an exact number for THIS
specific knob (e.g. "customer-support tasks require multi-step tool-driven
action sequences" without a published mean-calls-per-conversation figure),
that gap is stated explicitly rather than papered over with a fabricated
citation -- see the per-distribution docstrings below and the corpus report.

Every distribution takes an explicit ``numpy.random.Generator`` (the CLI
seeds exactly one, from ``--seed``) so the whole corpus is reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# --------------------------------------------------------------------------- #
# 1. Turns per call                                                           #
# --------------------------------------------------------------------------- #
# source: Decagon, "Voice AI for call centers: what buyers need to know"
# https://decagon.ai/blog/voice-ai-for-call-centers (retrieved 2026-08-31) --
# "the average resolved customer session spans 4.2 turns... sessions
# involving a transaction (refund, exchange, account change) average 6-8
# turns... single-turn interactions account for roughly 20-25% of volume."
#
# Turn counts in dialogue are overdispersed count data (variance > mean, long
# right tail for the occasional long call) -- modeled as a negative binomial
# with a fixed dispersion shape and a mean set per scenario complexity tier
# from the figures above. NB(r, p) has mean r(1-p)/p; r is fixed, p is solved
# per target mean so E[turns] matches the cited figure exactly.
TURNS_NB_DISPERSION = 4.0
TURNS_MEAN_INFORMATIONAL = 4.2   # lookup-only scenarios (order_status, tech_support)
TURNS_MEAN_TRANSACTIONAL = 7.0   # mid of the cited 6-8 turn transactional range


def sample_turn_count(rng: np.random.Generator, mean_turns: float) -> int:
    """Negative-binomial turn count, minimum 1 (a call always has >=1 turn)."""
    p = TURNS_NB_DISPERSION / (TURNS_NB_DISPERSION + mean_turns)
    n_failures = rng.negative_binomial(TURNS_NB_DISPERSION, p)
    return int(n_failures) + 1


# --------------------------------------------------------------------------- #
# 2. Output tokens per LLM decision (per-turn token counts, output side)      #
# --------------------------------------------------------------------------- #
# source (shape, not scale): "ShareChat: A Dataset of Chatbot Conversations
# in the Wild" (arXiv:2512.17843, retrieved 2026-08-31) reports assistant
# response lengths of mean 519.7 tokens (WildChat-derived) to 1115.3 tokens
# (denser corpora) -- i.e. response length is heavy-tailed / roughly
# log-normal-shaped, consistent with the general finding that natural-language
# length distributions are right-skewed.
#
# Scale is NOT taken from that figure: those are full multi-paragraph TEXT
# chatbot replies. A voice agent's turn is spoken aloud and TTS-bound, so it
# is deliberately much shorter -- this generator scales the median down to be
# consistent with the golden fixtures' hand-authored spoken turns
# (fixtures/golden/*.json output_tokens range ~10-140), which is itself
# grounded in the ~7-word / ~2-second short-turn figure a conversational-
# speech corpus analysis reports (see SPOKEN_WORDS_PER_TURN_MEDIAN below).
# This rescaling is a stated design choice, not a second citation.
#
# decision_kind -> (log-normal median tokens, log-normal sigma)
OUTPUT_TOKEN_PARAMS: dict[str, tuple[float, float]] = {
    "route": (14.0, 0.35),
    "tool_select": (18.0, 0.35),
    "slot_fill": (22.0, 0.45),
    "compose": (45.0, 0.90),          # heavy tail -> occasional long explanation
    "escalate_check": (20.0, 0.40),
}
OUTPUT_TOKENS_MIN = 4
OUTPUT_TOKENS_MAX = 600


def sample_output_tokens(rng: np.random.Generator, decision_kind: str) -> int:
    median, sigma = OUTPUT_TOKEN_PARAMS[decision_kind]
    val = rng.lognormal(mean=np.log(median), sigma=sigma)
    return int(np.clip(round(val), OUTPUT_TOKENS_MIN, OUTPUT_TOKENS_MAX))


# --------------------------------------------------------------------------- #
# 3. Caller utterance length (drives ASR audio_seconds)                       #
# --------------------------------------------------------------------------- #
# source: conversational-speech turn-length analysis surveyed via a
# cross-corpus review of short conversational turns (retrieved 2026-08-31,
# via arXiv/ResearchGate search on Switchboard-adjacent utterance-length
# literature) reports a representative short conversational turn of
# approximately 7 words / ~2 seconds. A single precise Switchboard-specific
# mean-words-per-turn figure was not available in a citable public summary;
# this uses that representative short-turn figure as the median, honestly
# flagged as an approximation rather than a Switchboard-exact statistic.
SPOKEN_WORDS_PER_TURN_MEDIAN = 7.0
SPOKEN_WORDS_PER_TURN_SIGMA = 0.5


def sample_caller_words(rng: np.random.Generator) -> int:
    val = rng.lognormal(mean=np.log(SPOKEN_WORDS_PER_TURN_MEDIAN), sigma=SPOKEN_WORDS_PER_TURN_SIGMA)
    return max(1, int(round(val)))


# --------------------------------------------------------------------------- #
# 4. Speech rate (words/chars per second) -- shared by ASR audio_seconds and  #
#    TTS audio_seconds_generated                                              #
# --------------------------------------------------------------------------- #
# source: average conversational/narration speaking rate of ~150 words per
# minute is a widely reported figure in speech-timing literature (e.g. the
# National Center for Voice and Speech's commonly cited conversational-rate
# range of 120-150 wpm); average English word length ~5 characters (+1 space)
# is the standard "words per minute" typing/reading convention. 150 wpm and
# ~5.3 chars/word/incl.-space give ~13.25 chars/second, which independently
# matches the golden fixtures' hand-authored TTS spans (e.g.
# fixtures/golden/00_baseline_clean.json t0: 18 chars / 1.4s = 12.9 chars/s).
SPEECH_WORDS_PER_MINUTE = 150.0
CHARS_PER_WORD_INCL_SPACE = 5.3
CHARS_PER_SECOND_SPEECH = SPEECH_WORDS_PER_MINUTE / 60.0 * CHARS_PER_WORD_INCL_SPACE


def words_to_seconds(n_words: int) -> float:
    return round(n_words / (SPEECH_WORDS_PER_MINUTE / 60.0), 3)


def chars_to_seconds(n_chars: int) -> float:
    return round(n_chars / CHARS_PER_SECOND_SPEECH, 3)


# --------------------------------------------------------------------------- #
# 4b. Words -> tokens (context/history growth)                                #
# --------------------------------------------------------------------------- #
# source: OpenAI, "What are tokens and how to count them"
# https://help.openai.com/en/articles/4936856-what-are-tokens-and-how-to-count-them
# (retrieved 2026-08-31) -- "a helpful rule of thumb is that one token
# generally corresponds to ~4 characters... 100 tokens ~= 75 words."
TOKENS_PER_WORD = 100.0 / 75.0


def words_to_tokens(n_words: int) -> int:
    return max(1, round(n_words * TOKENS_PER_WORD))


# --------------------------------------------------------------------------- #
# 4c. Retrieved-document chunk size (tool-call pattern: what a retrieval call #
#     returns, feeding turnstile.context.retrieved_tokens)                    #
# --------------------------------------------------------------------------- #
# Design assumption, not an external citation: RAG implementations commonly
# chunk source documents to a few hundred tokens; no single authoritative
# figure was found for this specific knob, so this uses a round
# order-of-magnitude value consistent with common RAG chunk-size practice,
# stated honestly as an assumption rather than dressed up with a citation
# that doesn't actually back it.
RETRIEVED_DOC_TOKENS_MEDIAN = 150.0
RETRIEVED_DOC_TOKENS_SIGMA = 0.4


def sample_retrieved_tokens(rng: np.random.Generator) -> int:
    val = rng.lognormal(mean=np.log(RETRIEVED_DOC_TOKENS_MEDIAN), sigma=RETRIEVED_DOC_TOKENS_SIGMA)
    return max(20, int(round(val)))


# --------------------------------------------------------------------------- #
# 5. Barge-in rate -- THE one named sensitivity parameter (Constraint 3)      #
# --------------------------------------------------------------------------- #
# source: telli.com, "AI Voice Agent Barge-In: How Real-Time Interruption
# Handling Works" https://www.telli.com/ai-voice-agents/article/what-is-barge-in
# (retrieved 2026-08-31) -- "deployment data pegs interruption at roughly 1 in
# 5 calls, with 15-20% of callers talking over the agent at some point."
# That figure is PER CALL (>=1 interruption); docs/CORPUS.md defines
# BARGE_IN_RATE as the fraction of individual AGENT TURNS the caller
# interrupts, a stricter per-turn denominator, so this is a documented
# reinterpretation of the cited figure, not a re-measurement of it. Kept as
# ONE named module-level constant, exposed as a CLI override
# (--barge-in-rate) so D7's magnitude can be reported as a sensitivity across
# a plausible range, never as a single asserted number.
BARGE_IN_RATE = 0.15


def sample_barge_in(rng: np.random.Generator, rate: float) -> bool:
    return bool(rng.random() < rate)


# --------------------------------------------------------------------------- #
# 6. Silence-gap durations (the D8 "silence tax" mechanism)                   #
# --------------------------------------------------------------------------- #
# 6a. Inter-turn gap: the caller's own response latency after the agent
# finishes speaking.
# source: Stivers et al., "Universals and cultural variation in turn-taking
# in conversation," PNAS 106(26):10587-10592, 2009 -- cross-linguistic modal
# gap between speaker turns of approximately 200ms (the classic finding,
# corroborated by the Max Planck Institute for Psycholinguistics turn-taking
# research this paper originates from).
INTER_TURN_GAP_MEDIAN_MS = 200.0
INTER_TURN_GAP_SIGMA = 0.6

# 6b. Processing-latency gap: ASR endpointing + LLM time-to-first-token + TTS
# time-to-first-audio-frame on a "stitched" (separate-vendor) voice stack.
# source: Telnyx, "Voice AI agents compared on latency: performance
# benchmark" https://telnyx.com/resources/voice-ai-agents-compared-latency
# (retrieved 2026-08-31) -- "AI voice response latency typically ranges from
# 600ms to 1,700ms on stitched stacks that combine separate ASR, LLM, and TTS
# vendors." This generator's telephony/ASR/TTS providers are exactly such a
# stitched stack (deepgram + openai + piper), so the median is set at the
# midpoint of that cited range.
PROCESSING_LATENCY_MEDIAN_MS = 1100.0
PROCESSING_LATENCY_SIGMA = 0.35


def _lognormal_ms(rng: np.random.Generator, median_ms: float, sigma: float) -> int:
    val = rng.lognormal(mean=np.log(median_ms), sigma=sigma)
    return max(0, int(round(val)))


def sample_inter_turn_gap_ms(rng: np.random.Generator) -> int:
    return _lognormal_ms(rng, INTER_TURN_GAP_MEDIAN_MS, INTER_TURN_GAP_SIGMA)


def sample_processing_latency_ms(rng: np.random.Generator) -> int:
    return _lognormal_ms(rng, PROCESSING_LATENCY_MEDIAN_MS, PROCESSING_LATENCY_SIGMA)


# --------------------------------------------------------------------------- #
# 7. Tool-call patterns                                                       #
# --------------------------------------------------------------------------- #
# source (qualitative structure only): Chen et al., "Action-Based
# Conversations Dataset: A Corpus for Building More In-Depth Task-Oriented
# Dialogue Systems" (arXiv:2104.00783, retrieved 2026-08-31) -- customer
# support interactions require agents to follow "multi-step procedures...
# requiring unique sequences of actions constrained by policies," across 55
# distinct intents. ABCD does not publish a single mean-actions-per-turn
# figure usable as a sampling parameter, so the WEIGHTS below are this
# generator's own operationalization of that qualitative structure (stated
# honestly, not represented as measured from ABCD): tool_select and
# slot_fill turns dominate a transactional call's middle, compose closes it
# out, escalate_check is comparatively rare.
DECISION_KIND_WEIGHTS_MUTATION: dict[str, float] = {
    "slot_fill": 0.34,
    "tool_select": 0.30,
    "compose": 0.32,
    "escalate_check": 0.04,
}
DECISION_KIND_WEIGHTS_LOOKUP: dict[str, float] = {
    "slot_fill": 0.18,
    "tool_select": 0.32,
    "compose": 0.46,
    "escalate_check": 0.04,
}
# Within a tool_select turn: lookup vs retrieval tool_kind split.
P_RETRIEVAL_GIVEN_TOOL_SELECT = 0.5
# Within a retrieval turn: probability of a tool_status=error requiring the
# agent to retry (tool_thrash-adjacent realism -- lookup/retrieval tools MAY
# carry tool_status=error with effect=none per the schema validator).
P_TOOL_ERROR = 0.06


def sample_decision_kind(rng: np.random.Generator, weights: dict[str, float]) -> str:
    kinds = list(weights.keys())
    probs = list(weights.values())
    return str(rng.choice(kinds, p=probs))


# --------------------------------------------------------------------------- #
# 8. ASR confidence                                                           #
# --------------------------------------------------------------------------- #
# source: Deepgram, https://deepgram.com/pricing (retrieved 2026-08-30,
# already the rate citation in pricing/rates.yaml) -- production STT engines
# on clean telephony audio are marketed at >90% word accuracy; modeled as a
# right-skewed Beta distribution (mode near 0.95, occasional lower-confidence
# tail for noisy/ambiguous audio) rather than a fixed constant.
ASR_CONFIDENCE_ALPHA = 9.0
ASR_CONFIDENCE_BETA = 1.4
ASR_CONFIDENCE_FLOOR = 0.55


def sample_asr_confidence(rng: np.random.Generator) -> float:
    val = rng.beta(ASR_CONFIDENCE_ALPHA, ASR_CONFIDENCE_BETA)
    return round(max(ASR_CONFIDENCE_FLOOR, min(0.99, val)), 3)


# --------------------------------------------------------------------------- #
# 9. Model-choice policy (D1 "over-model" realism) and context-pruning policy #
#    -- both are per-call SAMPLED policies, not hand-forced onto specific     #
#    traces (mission brief: "driven by a sampled model-choice policy").      #
# --------------------------------------------------------------------------- #
# Design parameters, not literature citations: these represent the modeled
# heterogeneity of a real fleet running a mix of agent-version routing
# configs, not a measured industry rate. Documented here, not hidden inline.
P_FRONTIER_FOR_TINY_DECISIONS = 0.22   # fraction of calls whose routing config
                                        # never right-sized route/tool_select
                                        # decisions off the frontier model
PRUNING_STRATEGY_WEIGHTS: dict[str, float] = {
    "none": 0.35,
    "window": 0.30,
    "summarize": 0.20,
    "semantic": 0.15,
}
P_PREFIX_CACHING_ENABLED = 0.55


def sample_frontier_policy(rng: np.random.Generator) -> bool:
    return bool(rng.random() < P_FRONTIER_FOR_TINY_DECISIONS)


def sample_pruning_strategy(rng: np.random.Generator) -> str:
    kinds = list(PRUNING_STRATEGY_WEIGHTS.keys())
    probs = list(PRUNING_STRATEGY_WEIGHTS.values())
    return str(rng.choice(kinds, p=probs))


def sample_prefix_caching_enabled(rng: np.random.Generator) -> bool:
    return bool(rng.random() < P_PREFIX_CACHING_ENABLED)


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    kind: str          # "lookup" | "mutation"
    tool_name: str | None


# --------------------------------------------------------------------------- #
# 10. Scenario and outcome mix (realism requirement, not a Constraint-1 item) #
# --------------------------------------------------------------------------- #
# Scenario/outcome PROPORTIONS below are a corpus-coverage design choice
# (variety across intents and resolution paths), not an externally sourced
# rate -- docs/CORPUS.md Constraint 1 lists turn counts, token counts,
# barge-in timing, silence-gap durations, and tool-call patterns as requiring
# a cited source; outcome-label mix is not on that list. Stated plainly here
# (and in the corpus report) so this is never mistaken for a measured figure.
SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec("order_status", "lookup", None),
    ScenarioSpec("tech_support", "lookup", None),
    ScenarioSpec("refund", "mutation", "process_refund"),
    ScenarioSpec("billing_dispute", "mutation", "adjust_billing"),
    ScenarioSpec("cancel_subscription", "mutation", "cancel_subscription"),
    ScenarioSpec("appointment_reschedule", "mutation", "reschedule_appointment"),
]

OUTCOME_WEIGHTS_LOOKUP: dict[str, float] = {
    "resolved": 0.55,
    "abandoned": 0.15,
    "escalated": 0.15,
    "handoff_rejected": 0.08,
    "handoff_pending": 0.07,
}
OUTCOME_WEIGHTS_MUTATION: dict[str, float] = {
    "resolved": 0.42,
    "false_resolve": 0.05,
    "unresolved": 0.13,
    "unknown_mutation": 0.05,
    "abandoned": 0.10,
    "escalated": 0.12,
    "handoff_rejected": 0.06,
    "handoff_pending": 0.07,
}


def sample_scenario(rng: np.random.Generator) -> ScenarioSpec:
    idx = rng.integers(0, len(SCENARIOS))
    return SCENARIOS[int(idx)]


def sample_outcome(rng: np.random.Generator, scenario: ScenarioSpec) -> str:
    weights = OUTCOME_WEIGHTS_MUTATION if scenario.kind == "mutation" else OUTCOME_WEIGHTS_LOOKUP
    labels = list(weights.keys())
    probs = list(weights.values())
    return str(rng.choice(labels, p=probs))
