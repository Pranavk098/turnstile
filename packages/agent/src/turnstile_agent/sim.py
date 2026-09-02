"""The streaming TTS generation/playback timeline with a modeled barge-in.

This is the spike's two-clock model (packages/agent/spikes/playback_probe.py,
kill-check PASSED), promoted: playback and generation are timed on SEPARATE
tracks so generation latency never poisons the playback position, and the
caller's interruption lands at a position on the HEARD-audio timeline.

The accounting (G2 by construction):
    intended   = characters in the full utterance
    generated  = characters actually synthesized before cancellation (BILLED)
    played     = characters whose audio elapsed before the interruption (HEARD)
    D7 waste   = generated - played   (billed but unheard)
    never_gen  = intended - generated (NOT billed -- excluded from waste)

WHAT IS MEASURED vs WHAT IS MODELED (the honesty line this module holds):

* MEASURED: every chunk's real audio duration and real wall-clock synthesis
  time, per chunk, from the injected engine (real Piper on this machine) --
  hence the generation-to-realtime ratio and the achieved generation-ahead
  lead at the moment of interruption. Phase 1 below measures the FULL
  utterance's chunk schedule ONCE; nothing the barge-in model does later can
  change it.
* MODELED (stated, swept, never a single tuned figure): WHETHER the caller
  barges in (a rate, sampled per call -- reported as a SWEEP over the cited
  range; the corpus's telli.com-cited 15% default anchors it) and WHERE on
  the heard-audio timeline the interruption lands (uniform over the
  utterance's audio duration -- the neutral null model; no citable position
  distribution was found, so rather than invent one, position is uniform and
  the rate sweep carries the uncertainty). The lead cap is a stated
  streaming-buffer policy, not a claim about any vendor.

Phase 2 REPLAYS the measured chunk schedule, so the barge-in behavior is
generated first and the measurement is taken second, reported as-is -- the
same rule the corpus holds. Deterministic given (engine schedule, B, lead
cap): same inputs -> identical accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from turnstile_agent.tts import SynthChunk, TtsEngine

# Stated streaming-buffer policy: audio-seconds of generated-but-unheard audio
# the pipeline allows before throttling generation. It caps how far ahead of
# playback the engine runs; combined with the MEASURED generation rate it
# determines the achieved lead at interruption. A stated harness parameter --
# the sweep is over the barge-in rate, not this.
DEFAULT_LEAD_CAP_S = 2.0

# Stated modeled duration for the scripted caller interrupt utterance (no ASR
# in scope; the interrupt line's audio length is an input, labeled as such).
CALLER_INTERRUPT_AUDIO_S = 0.8


@dataclass
class SimClock:
    """Explicitly-advanced monotonic-style clock (seconds since t0) driving
    the recorder's span offsets. The harness advances it by MEASURED wall
    time for synthesis steps and by MODELED audio time for playback steps;
    every span duration in the resulting trace is therefore truthful within
    its own domain, and G1's overlap arguments express the real streaming
    relationship."""

    _t: float = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += max(0.0, seconds)

    @property
    def seconds(self) -> float:
        return self._t


@dataclass(frozen=True)
class ChunkEvent:
    """One synthesized chunk (measured) with the generated-frontier position
    (audio-seconds) when its synthesis completed."""

    chars: int
    audio_seconds: float
    wall_seconds: float
    frontier_after_s: float


@dataclass(frozen=True)
class CallAccounting:
    """One call's character accounting plus the measured streaming facts."""

    utterance: str
    intended_chars: int
    generated_chars: int
    played_chars: int
    generated_audio_s: float
    generated_wall_s: float
    played_audio_s: float
    barge_in: bool
    barge_in_at_audio_s: float | None  # None when no barge-in
    truncated: bool
    achieved_lead_at_barge_in_s: float | None
    gen_rate_realtime_x: float  # MEASURED: generated audio_s / wall_s
    total_audio_s: float  # full utterance (measured phase-1 schedule)
    first_chunk_wall_s: float  # MEASURED: when first audio is ready (drives
    # the playback span's overlap with the tts span in the recorded trace)
    chunk_events: tuple[ChunkEvent, ...] = field(default_factory=tuple)

    @property
    def waste_chars(self) -> int:
        """D7's quantity: billed but unheard (0 when the caller never
        interrupts or hears everything)."""
        return self.generated_chars - self.played_chars


def measure_utterance(engine: TtsEngine, utterance: str) -> list[SynthChunk]:
    """Phase 1: synthesize the FULL utterance, recording each chunk's real
    audio duration and wall time. This is the measurement pass -- it runs
    once per call, before any barge-in behavior is sampled, so the schedule
    the accounting replays is independent of the modeled interruption."""
    return list(engine.synthesize_stream(utterance))


def simulate_call(
    engine: TtsEngine,
    utterance: str,
    *,
    barge_in_at_audio_s: float | None,
    lead_cap_s: float = DEFAULT_LEAD_CAP_S,
    schedule: list[SynthChunk] | None = None,
) -> CallAccounting:
    """Replay the streaming timeline for one call.

    ``schedule`` (phase-1 measurements) defaults to measuring it here. The
    caller interrupts after ``barge_in_at_audio_s`` of HEARD audio (None =
    never). Generation ahead of playback is capped at ``lead_cap_s``; a
    barge-in cancels all further generation, so chunks past the cancellation
    point are never synthesized and never billed (a chunk is atomic -- Piper
    synthesizes whole sentences -- mirroring a real pipeline's cancellation
    granularity)."""
    if schedule is None:
        schedule = measure_utterance(engine, utterance)
    if not schedule:
        raise ValueError("engine produced no audio for the utterance")

    total_audio_s = sum(c.audio_seconds for c in schedule)
    B = barge_in_at_audio_s
    if B is not None and B >= total_audio_s:
        # The interruption lands at/after the end of the readback: nothing
        # is actually cut off -- treat as no barge-in (played everything).
        B = None

    generated: list[ChunkEvent] = []
    frontier_s = 0.0
    played_s = 0.0
    played_chars = 0
    truncated = False
    achieved_lead: float | None = None

    def generate_ahead(target_frontier_s: float) -> None:
        """Pull chunks (billed) until the generated frontier reaches the
        lead-cap target ahead of what has been heard."""
        nonlocal frontier_s
        while frontier_s < target_frontier_s and len(generated) < len(schedule):
            chunk = schedule[len(generated)]
            frontier_s += chunk.audio_seconds
            generated.append(
                ChunkEvent(
                    chars=chunk.chars,
                    audio_seconds=chunk.audio_seconds,
                    wall_seconds=chunk.wall_seconds,
                    frontier_after_s=frontier_s,
                )
            )

    i = 0  # next chunk to play
    while True:
        generate_ahead(played_s + lead_cap_s)
        if i >= len(generated):
            break  # everything both generated and heard; nothing pending
        chunk = generated[i]
        if B is None or played_s + chunk.audio_seconds <= B:
            played_chars += chunk.chars
            played_s += chunk.audio_seconds
            i += 1
        else:
            # Barge-in lands mid-chunk (or at its start): the heard fraction
            # of THIS chunk plays, generation past the cancellation point is
            # cancelled -- chunks after `i` were never synthesized.
            frac = max(0.0, (B - played_s) / chunk.audio_seconds)
            played_chars += int(chunk.chars * frac)
            played_s += frac * chunk.audio_seconds
            truncated = True
            achieved_lead = max(0.0, frontier_s - played_s)
            break

    generated_audio_s = sum(c.audio_seconds for c in generated)
    generated_wall_s = sum(c.wall_seconds for c in generated)
    gen_rate = generated_audio_s / generated_wall_s if generated_wall_s > 0 else 0.0

    return CallAccounting(
        utterance=utterance,
        # "Intended" = the text as actually chunked for synthesis (sentence
        # chunks; the inter-sentence whitespace is not a billed unit). G2's
        # invariant reads against this stream: intended >= generated >= played.
        intended_chars=sum(c.chars for c in schedule),
        generated_chars=sum(c.chars for c in generated),
        played_chars=played_chars,
        generated_audio_s=generated_audio_s,
        generated_wall_s=generated_wall_s,
        played_audio_s=played_s,
        barge_in=B is not None,
        barge_in_at_audio_s=B,
        truncated=truncated,
        achieved_lead_at_barge_in_s=achieved_lead,
        gen_rate_realtime_x=gen_rate,
        total_audio_s=total_audio_s,
        first_chunk_wall_s=schedule[0].wall_seconds,
        chunk_events=tuple(generated),
    )


def sample_barge_in_position(
    rng: "object",
    total_audio_s: float,
) -> float:
    """MODELED interruption position: uniform over the utterance's audio
    duration (the stated null model -- see module docstring). ``rng`` is a
    ``numpy.random.Generator``."""
    return float(rng.uniform(0.0, total_audio_s))
