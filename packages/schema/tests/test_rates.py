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
