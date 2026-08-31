"""Synthetic trace generator (packages/corpus mission, docs/CORPUS.md).

``generate_corpus(n, seed) -> list[Trace]`` is the pure, deterministic entry
point; ``main()`` is the CLI wrapper that writes one schema-v1.1 JSON file
per trace. This module is built to satisfy the three binding constraints in
docs/CORPUS.md:

  1. Sample, don't choose -- every stochastic quantity (turn counts, per-turn
     token counts, barge-in timing, silence-gap durations, tool-call
     patterns) is drawn from a named, cited ``turnstile_corpus.distributions
     .sample_*()`` call. This module holds no hand-picked magic values for
     those quantities; only minor, uncited implementation constants (e.g.
     tool/LLM wall-clock latency ranges, a fixed system-prompt size) live
     here, documented as such.
  2. Do not tune to the detectors -- this module (and distributions.py) has
     ZERO import of ``turnstile_detectors``. Generation happens first and
     independently; ``packages/corpus/tests/test_generate.py`` asserts the
     absence of that import by source inspection. Whatever waste patterns
     the cited distributions produce is reported, not engineered.
  3. Barge-in rate is ONE named parameter --
     ``turnstile_corpus.distributions.BARGE_IN_RATE`` -- overridable via
     ``--barge-in-rate`` / the ``barge_in_rate`` kwarg, so its effect can be
     reported as a sensitivity across a plausible range.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from turnstile_schema import (
    AsrTranscribe,
    AudioPlayback,
    Conversation,
    ContextAssemble,
    LlmDecide,
    TelephonyLeg,
    ToolCall,
    Trace,
    TtsSynthesize,
    Turn,
)
from turnstile_schema.enums import (
    Direction,
    Effect,
    EndReason,
    DecisionKind,
    PruningStrategy,
    SpeakerFirst,
    ToolKind,
    ToolStatus,
)

from turnstile_corpus import distributions as dist

# --------------------------------------------------------------------------- #
# Minor, uncited implementation constants (wall-clock realism only -- none of #
# these drive which waste patterns appear or how often; see module docstring #
# and the corpus report for the constants that DO, which all live in         #
# distributions.py with a cited source).                                     #
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT_TOKENS = 220
CONTEXT_ASSEMBLE_DURATION_MS = 80
LLM_LATENCY_MS_RANGE = (300, 900)
TOOL_LATENCY_MS_RANGE = (150, 450)
CACHE_READ_FRACTION_OF_HISTORY = 0.8
BARGE_IN_TRUNCATION_FRACTION_RANGE = (0.10, 0.70)
RETRIEVAL_DOC_POOL_SIZE = 4
AGENT_VERSION = "agent@corpus-v1"
TELEPHONY_PROVIDER = "twilio"

TOOL_KIND_LOOKUP = ToolKind.lookup
TOOL_KIND_RETRIEVAL = ToolKind.retrieval

# Text templates -- flavor content only, not a sampled quantity.
TEXT_ROUTE = "Let me look into that for you."
TEXT_SLOT_FILL = "Can you confirm the account details for me?"
TEXT_SLOT_FILL_ABANDONED = "I still need your account number to continue -- are you there?"
TEXT_TOOL_SELECT_COMPOSE = "One moment while I check on that."
TEXT_COMPOSE_INFO = "Here is what I found for you."
TEXT_CLOSE_RESOLVED = "Anything else I can help with? Have a great day!"
TEXT_MUTATION_RESOLVED = "I've gone ahead and completed that for you."
TEXT_MUTATION_FALSE_RESOLVE = "That has been processed and is all set."
TEXT_MUTATION_UNRESOLVED = "We'll need to follow up on that shortly."
TEXT_MUTATION_UNKNOWN = "We're having trouble confirming that right now."
TEXT_ESCALATE_STALL = "Let me keep looking into this."
TEXT_ESCALATE_COMMITTED = "I'm connecting you with a specialist now."
TEXT_HANDOFF_REJECTED = "I'm sorry, all our specialists are unavailable right now."
TEXT_HANDOFF_PENDING = "You're being placed in the queue for the next available specialist."
TEXT_CALLER_UTTERANCE = "Caller utterance for turn {turn}."

MUTATION_OUTCOMES = {"resolved", "false_resolve", "unresolved", "unknown_mutation"}
HANDOFF_OUTCOMES = {"escalated", "handoff_rejected", "handoff_pending"}


def _effective_history_tokens(accum: int, strategy: str) -> int:
    if strategy == "none":
        return accum
    if strategy == "window":
        return min(accum, 1200)
    # summarize / semantic: compressed representation of older history
    return min(int(accum * 0.35), 1200)


def _mutation_effect_and_status(outcome: str) -> tuple[Effect, ToolStatus, str]:
    if outcome == "resolved":
        return Effect.committed, ToolStatus.ok, TEXT_MUTATION_RESOLVED
    if outcome == "false_resolve":
        return Effect.rejected, ToolStatus.ok, TEXT_MUTATION_FALSE_RESOLVE
    if outcome == "unresolved":
        return Effect.pending, ToolStatus.ok, TEXT_MUTATION_UNRESOLVED
    if outcome == "unknown_mutation":
        return Effect.unknown, ToolStatus.error, TEXT_MUTATION_UNKNOWN
    raise ValueError(f"not a mutation outcome: {outcome}")


def _handoff_effect_and_status(outcome: str) -> tuple[Effect, ToolStatus, str]:
    if outcome == "escalated":
        return Effect.committed, ToolStatus.ok, TEXT_ESCALATE_COMMITTED
    if outcome == "handoff_rejected":
        return Effect.rejected, ToolStatus.ok, TEXT_HANDOFF_REJECTED
    if outcome == "handoff_pending":
        return Effect.pending, ToolStatus.ok, TEXT_HANDOFF_PENDING
    raise ValueError(f"not a handoff outcome: {outcome}")


def _build_turn(
    rng: np.random.Generator,
    *,
    turn_index: int,
    cursor_ms: int,
    speaker_first: SpeakerFirst,
    decision_kind: DecisionKind,
    decision_chosen: str,
    decision_candidates: list[str],
    output_text: str,
    tool_kind: ToolKind | None,
    tool_name: str | None,
    tool_effect: Effect,
    tool_status: ToolStatus,
    history_tokens_accum: int,
    pruning_strategy: str,
    caching_enabled: bool,
    frontier_policy: bool,
    barge_in_rate: float,
    doc_pool: list[str],
    seen_docs: set[str],
    span_seq: list[int],
) -> tuple[Turn, int, int]:
    """Build one Turn; returns (turn, new_cursor_ms, new_history_tokens_accum)."""

    def next_span_id(prefix: str) -> str:
        span_seq[0] += 1
        return f"{prefix}{span_seq[0]}"

    t = cursor_ms
    gap1 = dist.sample_inter_turn_gap_ms(rng)
    t += gap1

    asr_spans: list[AsrTranscribe] = []
    asr_tokens = 0
    if speaker_first == SpeakerFirst.caller:
        n_words = dist.sample_caller_words(rng)
        audio_seconds = dist.words_to_seconds(n_words)
        asr_tokens = dist.words_to_tokens(n_words)
        confidence = dist.sample_asr_confidence(rng)
        dur_ms = max(1, round(audio_seconds * 1000))
        asr_spans.append(
            AsrTranscribe(
                span_id=next_span_id("a"),
                start_offset_ms=t,
                duration_ms=dur_ms,
                gen_ai_system="deepgram",
                gen_ai_request_model="nova-3",
                audio_seconds=audio_seconds,
                is_streaming=True,
                transcript=TEXT_CALLER_UTTERANCE.format(turn=turn_index),
                confidence=confidence,
            )
        )
        t += dur_ms

    gap2 = dist.sample_processing_latency_ms(rng)
    t += gap2

    tools: list[ToolCall] = []
    retrieved_tokens = 0
    retrieved_doc_ids: list[str] = []
    if tool_kind is not None:
        tool_dur = int(rng.uniform(*TOOL_LATENCY_MS_RANGE))
        result_hash = f"sha256:r{next_span_id('')}"
        # args_hash is a hash of the call's actual arguments, so it is
        # DETERMINISTIC per (tool_name[, doc]) rather than a fresh value per
        # call -- a real duplicate call (same tool, same target, e.g. a retry
        # after tool_status=error or a redundant repeat) genuinely hashes the
        # same both times. This is what lets Detector 10 (tool thrash) see a
        # real repeat when the sampled decision sequence happens to produce
        # one, instead of every call being artificially unique by
        # construction.
        args_hash = f"sha256:args_{tool_name}"
        args_json = "{}"
        if tool_kind is TOOL_KIND_RETRIEVAL:
            # Doc id chosen from a small per-scenario pool BEFORE building the
            # call, and embedded in args_json -- the schema convention
            # packages/detectors/d03_redundant_retrieval.py reads a
            # retrieval's doc id from (fixtures/golden's own authoring
            # convention: {"query": ..., "doc_id": ...}), not a dedicated
            # ToolCall field.
            chosen_doc = str(rng.choice(doc_pool))
            retrieved_doc_ids = [chosen_doc]
            seen_docs.add(chosen_doc)
            retrieved_tokens = dist.sample_retrieved_tokens(rng)
            args_json = json.dumps({"query": tool_name, "doc_id": chosen_doc})
            args_hash = f"sha256:args_{tool_name}_{chosen_doc}"
        tools.append(
            ToolCall(
                span_id=next_span_id("tool"),
                start_offset_ms=t,
                duration_ms=tool_dur,
                tool_name=tool_name or "unknown_tool",
                args_hash=args_hash,
                args_json=args_json,
                result_hash=result_hash,
                latency_ms=tool_dur,
                tool_kind=tool_kind,
                tool_status=tool_status,
                effect=tool_effect,
            )
        )
        t += tool_dur

    pre_accum = history_tokens_accum + asr_tokens
    effective_history = _effective_history_tokens(pre_accum, pruning_strategy)
    context_tokens = SYSTEM_PROMPT_TOKENS + effective_history + retrieved_tokens
    context = ContextAssemble(
        span_id=next_span_id("c"),
        start_offset_ms=t,
        duration_ms=CONTEXT_ASSEMBLE_DURATION_MS,
        context_tokens=context_tokens,
        history_tokens=effective_history,
        system_tokens=SYSTEM_PROMPT_TOKENS,
        retrieved_tokens=retrieved_tokens,
        retrieved_doc_ids=retrieved_doc_ids,
        pruning_strategy=PruningStrategy(pruning_strategy),
    )
    t += CONTEXT_ASSEMBLE_DURATION_MS

    output_tokens = dist.sample_output_tokens(rng, decision_kind.value)
    cache_read_tokens = 0
    if caching_enabled and effective_history > 0:
        cache_read_tokens = min(
            round(effective_history * CACHE_READ_FRACTION_OF_HISTORY), context_tokens - 1
        )
        cache_read_tokens = max(0, cache_read_tokens)

    is_tiny_decision = decision_kind in (DecisionKind.route, DecisionKind.tool_select)
    if is_tiny_decision:
        model = "gpt-5" if frontier_policy else str(rng.choice(["gpt-5-mini", "gpt-5-nano"], p=[0.7, 0.3]))
    else:
        model = "gpt-5" if (output_tokens > 100 and rng.random() < 0.4) else "gpt-5-mini"

    llm_dur = int(rng.uniform(*LLM_LATENCY_MS_RANGE))
    llm = LlmDecide(
        span_id=next_span_id("l"),
        start_offset_ms=t,
        duration_ms=llm_dur,
        gen_ai_system="openai",
        gen_ai_request_model=model,
        input_tokens=context_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        decision_kind=decision_kind,
        decision_chosen=decision_chosen,
        decision_candidates=decision_candidates,
        output_text=output_text,
        latency_ms=llm_dur,
    )
    t += llm_dur

    chars = len(output_text)
    tts_seconds = dist.chars_to_seconds(chars)
    tts_dur = max(1, round(tts_seconds * 1000))
    tts = TtsSynthesize(
        span_id=next_span_id("t"),
        start_offset_ms=t,
        duration_ms=tts_dur,
        gen_ai_system="piper",
        chars_synthesized=chars,
        audio_seconds_generated=tts_seconds,
        text=output_text,
    )
    t += tts_dur

    barge_in = dist.sample_barge_in(rng, barge_in_rate)
    if barge_in and chars > 1:
        frac = rng.uniform(*BARGE_IN_TRUNCATION_FRACTION_RANGE)
        chars_played = max(1, int(chars * frac))
        played_seconds = dist.chars_to_seconds(chars_played)
        playback_dur = max(1, round(played_seconds * 1000))
        truncated_by = "barge_in"
    else:
        barge_in = False
        chars_played = chars
        played_seconds = tts_seconds
        playback_dur = tts_dur
        truncated_by = None

    playback = AudioPlayback(
        span_id=next_span_id("p"),
        start_offset_ms=t,
        duration_ms=playback_dur,
        chars_played=chars_played,
        audio_seconds_played=played_seconds,
        truncated_by=truncated_by,
    )
    t += playback_dur

    wall_end = t
    new_history_accum = pre_accum + output_tokens

    turn = Turn(
        turn_index=turn_index,
        speaker_first=speaker_first,
        wall_start_ms=cursor_ms,
        wall_end_ms=wall_end,
        barge_in=barge_in,
        vad=[],
        asr=asr_spans,
        context=context,
        llm=[llm],
        tools=tools,
        tts=[tts],
        playback=[playback],
    )
    return turn, wall_end, new_history_accum


def _generate_trace(rng: np.random.Generator, index: int, seed: int, barge_in_rate: float) -> Trace:
    scenario = dist.sample_scenario(rng)
    outcome = dist.sample_outcome(rng, scenario)
    mean_turns = (
        dist.TURNS_MEAN_TRANSACTIONAL if scenario.kind == "mutation" else dist.TURNS_MEAN_INFORMATIONAL
    )
    n_turns = dist.sample_turn_count(rng, mean_turns)

    frontier_policy = dist.sample_frontier_policy(rng)
    pruning_strategy = dist.sample_pruning_strategy(rng)
    caching_enabled = dist.sample_prefix_caching_enabled(rng)
    decision_weights = dist.DECISION_KIND_WEIGHTS_MUTATION if scenario.kind == "mutation" else dist.DECISION_KIND_WEIGHTS_LOOKUP

    is_mutation_outcome = outcome in MUTATION_OUTCOMES and scenario.kind == "mutation"
    is_handoff_outcome = outcome in HANDOFF_OUTCOMES
    last_turn_idx = n_turns - 1

    escalate_turn_idx: int | None = None
    if is_handoff_outcome:
        escalate_turn_idx = int(rng.integers(0, n_turns - 1)) if n_turns >= 2 else last_turn_idx

    doc_pool = [f"doc_{scenario.scenario_id}_{k}" for k in range(RETRIEVAL_DOC_POOL_SIZE)]
    seen_docs: set[str] = set()

    cursor_ms = 0
    history_tokens_accum = 0
    span_seq = [0]
    turns: list[Turn] = []

    for i in range(n_turns):
        is_last = i == last_turn_idx
        is_terminal_handoff = is_handoff_outcome and is_last
        is_early_escalate_check = escalate_turn_idx is not None and i == escalate_turn_idx and not is_last
        is_terminal_mutation = is_mutation_outcome and is_last

        if i == 0:
            speaker_first = SpeakerFirst.caller
        else:
            speaker_first = SpeakerFirst.caller if rng.random() < 0.95 else SpeakerFirst.agent

        tool_kind: ToolKind | None = None
        tool_name: str | None = None
        tool_effect = Effect.none
        tool_status = ToolStatus.ok

        if is_terminal_handoff:
            decision_kind = DecisionKind.escalate_check
            decision_chosen = "escalate"
            decision_candidates = ["resolve", "escalate"]
            tool_effect, tool_status, output_text = _handoff_effect_and_status(outcome)
            tool_kind = ToolKind.handoff
            tool_name = "transfer_to_agent"
        elif is_early_escalate_check:
            decision_kind = DecisionKind.escalate_check
            decision_chosen = "continue"
            decision_candidates = ["continue", "escalate"]
            output_text = TEXT_ESCALATE_STALL
        elif is_terminal_mutation:
            decision_kind = DecisionKind.compose
            decision_chosen = "complete_mutation"
            decision_candidates = ["complete_mutation"]
            tool_effect, tool_status, output_text = _mutation_effect_and_status(outcome)
            tool_kind = ToolKind.mutation
            tool_name = scenario.tool_name
        elif is_last and outcome == "abandoned":
            decision_kind = DecisionKind.slot_fill
            decision_chosen = "request_slot"
            decision_candidates = ["request_slot"]
            output_text = TEXT_SLOT_FILL_ABANDONED
        elif is_last and outcome == "resolved":
            decision_kind = DecisionKind.compose
            decision_chosen = "close_call"
            decision_candidates = ["close_call"]
            output_text = TEXT_CLOSE_RESOLVED
        elif i == 0:
            decision_kind = DecisionKind.route
            decision_chosen = scenario.scenario_id
            decision_candidates = [scenario.scenario_id, "other"]
            output_text = TEXT_ROUTE
        else:
            decision_kind = DecisionKind(dist.sample_decision_kind(rng, decision_weights))
            if decision_kind == DecisionKind.slot_fill:
                decision_chosen = "request_slot"
                decision_candidates = ["request_slot"]
                output_text = TEXT_SLOT_FILL
            elif decision_kind == DecisionKind.tool_select:
                is_retrieval = rng.random() < dist.P_RETRIEVAL_GIVEN_TOOL_SELECT
                tool_kind = TOOL_KIND_RETRIEVAL if is_retrieval else TOOL_KIND_LOOKUP
                tool_name = "retrieve_kb_article" if is_retrieval else "lookup_account"
                tool_status = ToolStatus.error if rng.random() < dist.P_TOOL_ERROR else ToolStatus.ok
                tool_effect = Effect.none
                decision_chosen = tool_name
                decision_candidates = [tool_name]
                output_text = TEXT_TOOL_SELECT_COMPOSE
            elif decision_kind == DecisionKind.escalate_check:
                decision_chosen = "continue"
                decision_candidates = ["continue", "escalate"]
                output_text = TEXT_ESCALATE_STALL
            else:  # compose
                decision_chosen = "inform"
                decision_candidates = ["inform"]
                output_text = TEXT_COMPOSE_INFO

        turn, cursor_ms, history_tokens_accum = _build_turn(
            rng,
            turn_index=i,
            cursor_ms=cursor_ms,
            speaker_first=speaker_first,
            decision_kind=decision_kind,
            decision_chosen=decision_chosen,
            decision_candidates=decision_candidates,
            output_text=output_text,
            tool_kind=tool_kind,
            tool_name=tool_name,
            tool_effect=tool_effect,
            tool_status=tool_status,
            history_tokens_accum=history_tokens_accum,
            pruning_strategy=pruning_strategy,
            caching_enabled=caching_enabled,
            frontier_policy=frontier_policy,
            barge_in_rate=barge_in_rate,
            doc_pool=doc_pool,
            seen_docs=seen_docs,
            span_seq=span_seq,
        )
        turns.append(turn)

    end_reason = EndReason.escalated if outcome == "escalated" else EndReason.caller_hangup

    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    ended_at = started_at + timedelta(milliseconds=cursor_ms)
    conversation_id = f"corpus-{seed}-{index:05d}"

    conversation = Conversation(
        conversation_id=conversation_id,
        agent_version=AGENT_VERSION,
        scenario_id=scenario.scenario_id,
        started_at=started_at,
        ended_at=ended_at,
        end_reason=end_reason,
    )
    telephony = TelephonyLeg(
        span_id="leg",
        start_offset_ms=0,
        duration_ms=cursor_ms,
        provider=TELEPHONY_PROVIDER,
        direction=Direction.inbound,
        billable_seconds=max(1, round(cursor_ms / 1000)),
    )
    return Trace(conversation=conversation, turns=turns, telephony=telephony)


def generate_corpus(n: int, seed: int, barge_in_rate: float | None = None) -> list[Trace]:
    """Deterministic entry point: same (n, seed, barge_in_rate) -> same corpus.

    ``barge_in_rate`` defaults to ``distributions.BARGE_IN_RATE`` (docs/
    CORPUS.md Constraint 3: barge-in rate is ONE named parameter).
    """
    rate = dist.BARGE_IN_RATE if barge_in_rate is None else barge_in_rate
    rng = np.random.default_rng(seed)
    return [_generate_trace(rng, i, seed, rate) for i in range(n)]


def _write_corpus(traces: list[Trace], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for trace in traces:
        path = out_dir / f"{trace.conversation.conversation_id}.json"
        path.write_text(
            json.dumps(trace.model_dump(by_alias=True, mode="json"), indent=2),
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic Turnstile corpus.")
    parser.add_argument("--n", type=int, default=250, help="number of traces to generate")
    parser.add_argument("--seed", type=int, default=0, help="RNG seed (deterministic)")
    parser.add_argument("--out", type=str, default="corpus/", help="output directory")
    parser.add_argument(
        "--barge-in-rate",
        type=float,
        default=None,
        help="override distributions.BARGE_IN_RATE (fraction of agent turns interrupted)",
    )
    args = parser.parse_args(argv)

    traces = generate_corpus(args.n, args.seed, barge_in_rate=args.barge_in_rate)
    _write_corpus(traces, Path(args.out))
    print(f"wrote {len(traces)} traces to {args.out} (seed={args.seed})")


if __name__ == "__main__":
    main()
