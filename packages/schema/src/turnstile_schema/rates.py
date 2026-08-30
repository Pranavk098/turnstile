from __future__ import annotations
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
