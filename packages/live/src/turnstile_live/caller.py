"""Synthetic interruption-heavy caller (Phase 4): the proposal's "impatient
caller" as a seeded sampler. Per agent-TTS turn it decides whether the caller
barges in mid-playback and at what audio fraction -- both drawn from a numpy
Generator, so the behavior is deterministic under a seed and swept (not
tuned) across runs. Caller utterance texts stay scripted (the sampler only
controls interruption, never content).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from turnstile_corpus.distributions import sample_inter_turn_gap_ms


@dataclass(frozen=True)
class ImpatientCaller:
    """p_barge: per agent turn, P(caller interrupts mid-playback).
    pos_lo/pos_hi: the interruption position (fraction of the agent's
    synthesized audio elapsed when the caller cuts in), Uniform draw.
    seed: determinism source for both draws, consumed in call order."""

    p_barge: float
    pos_lo: float = 0.25
    pos_hi: float = 0.75
    seed: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.p_barge <= 1.0:
            raise ValueError(f"p_barge must be in [0, 1], got {self.p_barge}")
        if not 0.0 < self.pos_lo <= self.pos_hi < 1.0:
            raise ValueError(
                f"position window must sit inside (0, 1), got {(self.pos_lo, self.pos_hi)}"
            )
        object.__setattr__(self, "_rng", np.random.default_rng(self.seed))

    def maybe_barge_in(self) -> float | None:
        """None = full playback; else the interruption fraction in
        [pos_lo, pos_hi]. Draw order is fixed (bernoulli, then position)."""
        rng = self.__dict__["_rng"]
        if rng.random() >= self.p_barge:
            return None
        return float(rng.uniform(self.pos_lo, self.pos_hi))

    def gap_ms(self) -> int:
        """Inter-turn response gap: the corpus's cited lognormal (Stivers et
        al. 2009, median ~200ms) drawn from this caller's own stream -- the
        fixed 300ms floor that made D8 constant is gone."""
        return sample_inter_turn_gap_ms(self.__dict__["_rng"])

    def processing_gap_ms(self) -> int:
        """ASR->LLM handoff silence: the corpus's cited processing-latency
        lognormal (Telnyx stitched-stack benchmark, median ~1100ms). Real
        dead air inside the turn, which D8 can see (inter-turn gaps sit
        between turn walls, outside D8's per-turn union)."""
        from turnstile_corpus.distributions import sample_processing_latency_ms

        return sample_processing_latency_ms(self.__dict__["_rng"])

    def utterance(self, turn_index: int, script: tuple[str, ...] | list[str]) -> str:
        """The scripted caller text for this turn (clamped to the script)."""
        return script[min(turn_index, len(script) - 1)]
