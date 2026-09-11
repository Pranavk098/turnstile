"""Voice-loop tests: injected fake engines (no Piper/Whisper/network), real
ingest validation + pipeline. The live run (real engines) is manual; these
pin the loop's structure, honesty invariants, and determinism."""
from __future__ import annotations

from pathlib import Path
import wave

from turnstile_ingest import describe_coverage, parse_call, run_call
from turnstile_schema import Baselines, load_rates

from turnstile_live.loop import SCRIPTED_DEMO_TURNS
from turnstile_live.voice import (
    LlmDecision,
    TtsObservation,
    run_voice_conversation,
)

ROOT = Path(__file__).parents[3]
RATES = load_rates(ROOT / "pricing" / "rates.yaml")
BASELINES = Baselines.model_validate_json(
    (ROOT / "fixtures" / "sample" / "baselines.json").read_text(encoding="utf-8")
)


class FakeStt:
    """Returns one canned transcript per call; duration measured from the
    wav itself (stdlib wave -- the one real measurement here)."""

    def __init__(self, transcripts: list[str]) -> None:
        self._transcripts = list(transcripts)
        self.calls = 0

    def transcribe_wav(self, path: Path) -> tuple[str, float]:
        with wave.open(str(path), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
        text = self._transcripts[min(self.calls, len(self._transcripts) - 1)]
        self.calls += 1
        return text, seconds


class FakeTts:
    """Writes silent wavs of fixed length; reports len(text) chars as FAKE
    accounting (test-only -- the live path uses engine-measured counts)."""

    def __init__(self, audio_seconds: float = 2.0, sample_rate: int = 22050) -> None:
        self.audio_seconds = audio_seconds
        self.sample_rate = sample_rate

    def synth_to_wav(self, text: str, path: Path) -> TtsObservation:
        import struct

        n = int(self.audio_seconds * self.sample_rate)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(struct.pack(f"<{n}h", *([0] * n)))
        return TtsObservation(
            chars_synthesized=len(text), chars_played=len(text),
            audio_seconds=self.audio_seconds, wall_seconds=0.05,
        )


class FakeLlm:
    """Canned route -> tool -> close sequence mirroring the demo script."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, scenario, transcript, turn_index, candidates):
        self.calls += 1
        if turn_index == 0:
            return LlmDecision("route", "billing_dispute", "Let me look into that bill for you.", 700, 20, False)
        if turn_index == 1:
            return LlmDecision("tool_select", "lookup_invoices", "Pulling up the invoice now.", 800, 15, False)
        return LlmDecision("compose", "close_call", "Glad I could help — anything else today?", 850, 18, False)


def _run(tmp_path: Path):
    stt = FakeStt(list(SCRIPTED_DEMO_TURNS))
    tts = FakeTts()
    llm = FakeLlm()
    call, report = run_voice_conversation(
        call_id="live-voice-001", scenario="billing_dispute",
        caller_texts=list(SCRIPTED_DEMO_TURNS),
        stt=stt, tts=tts, llm=llm, audio_dir=tmp_path / "audio",
    )
    return call, report, stt, llm


def test_voice_call_validates_as_ingest(tmp_path):
    call, _report, _stt, _llm = _run(tmp_path)
    parsed = parse_call(call.model_dump(mode="json"))
    assert parsed.id == "live-voice-001"
    assert len(parsed.turns) == 3
    for turn, expected in zip(parsed.turns, SCRIPTED_DEMO_TURNS):
        assert turn.asr.transcript == expected
        assert turn.tts.chars_synthesized == len(turn.tts.text)
        assert turn.tts.chars_played == len(turn.tts.text)


def test_voice_call_has_measured_acoustic_coverage(tmp_path):
    call, _report, _stt, _llm = _run(tmp_path)
    coverage = describe_coverage(call)
    assert coverage[6]["status"] == "present"
    assert coverage[7]["status"] == "present"
    assert coverage[8]["status"] == "present"


def test_pipeline_resolves_the_voice_call(tmp_path):
    call, _report, _stt, _llm = _run(tmp_path)
    result = run_call(call.model_dump(mode="json"), RATES, BASELINES)
    assert result["conv_cost_usd"] > 0.0
    assert result["verdict"]["label"] == "RESOLVED"


def test_voice_run_writes_audio_and_reports_provenance(tmp_path):
    call, report, stt, llm = _run(tmp_path)
    assert stt.calls == 3 and llm.calls == 3
    assert len(report["caller_wavs"]) == 3
    assert len(report["agent_wavs"]) == 3
    for wav in report["caller_wavs"] + report["agent_wavs"]:
        assert Path(wav).exists()
    assert report["agent_version"] == call.agent_version
    assert all(not t["llm_fallback"] for t in report["turns"])


def test_voice_conversation_is_deterministic(tmp_path):
    first, _ = run_voice_conversation(
        call_id="live-voice-001", scenario="billing_dispute",
        caller_texts=list(SCRIPTED_DEMO_TURNS),
        stt=FakeStt(list(SCRIPTED_DEMO_TURNS)), tts=FakeTts(), llm=FakeLlm(),
        audio_dir=tmp_path / "a",
    )
    second, _ = run_voice_conversation(
        call_id="live-voice-001", scenario="billing_dispute",
        caller_texts=list(SCRIPTED_DEMO_TURNS),
        stt=FakeStt(list(SCRIPTED_DEMO_TURNS)), tts=FakeTts(), llm=FakeLlm(),
        audio_dir=tmp_path / "b",
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
