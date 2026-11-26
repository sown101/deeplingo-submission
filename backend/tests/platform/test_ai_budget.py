"""The daily cap on paid AI spend (owner 2026-11-18): prices, the counter, and every paid path refusing once
the cap is reached. Fakes only: no provider, no Redis."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.platform.ai_budget import DailyBudget, live_cost, speech_cost, text_cost, tts_cost
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory


def test_prices_follow_the_list_and_an_unknown_model_costs_more():
    assert text_cost("gemini-3.5-flash-lite", 1_000_000, 1_000_000) == pytest.approx(2.80)
    assert text_cost("some-new-model", 1_000_000, 0) > text_cost("gemini-3.5-flash-lite", 1_000_000, 0)
    assert live_cost(60, 60) == pytest.approx(0.023)  # a minute of audio each way
    assert speech_cost(3600) == pytest.approx(1.30) and tts_cost(1_000_000) == pytest.approx(15.0)
    assert text_cost("gemini-3.5-flash-lite", -5, -5) == 0 and live_cost(-1, -1) == 0


def test_the_counter_refuses_at_the_cap_and_starts_again_the_next_day():
    day = [date(2026, 11, 18)]
    budget = DailyBudget(cap_usd=2.0, today=lambda: day[0])
    budget.charge(1.5)
    assert budget.allows() and budget.spent() == pytest.approx(1.5)
    budget.charge(0.5)
    assert not budget.allows()
    day[0] = date(2026, 11, 19)
    assert budget.allows() and budget.spent() == 0
    assert DailyBudget(cap_usd=0).allows()  # 0 turns the guard off


class FakeRedis:
    def __init__(self, broken=False):
        self.values, self.broken, self.expiry = {}, broken, {}

    def get(self, key):
        if self.broken:
            raise ConnectionError("down")
        return self.values.get(key)

    def incrby(self, key, amount):
        if self.broken:
            raise ConnectionError("down")
        self.values[key] = self.values.get(key, 0) + amount

    def expire(self, key, seconds):
        self.expiry[key] = seconds


def test_processes_share_the_counter_through_redis_and_refuse_when_it_fails():
    shared = FakeRedis()
    api, worker = (DailyBudget(cap_usd=1.0, redis=shared, today=lambda: date(2026, 11, 18)) for _ in range(2))
    api.charge(0.6)
    worker.charge(0.6)
    assert not api.allows() and shared.expiry["ai:spend:2026-11-18"] == 3 * 24 * 3600
    lonely = DailyBudget(cap_usd=1.0, redis=FakeRedis(broken=True))
    assert not lonely.allows()
    assert lonely.reserve(0.1) is None
    assert DailyBudget(cap_usd=1.0, require_redis=True).reserve(0.1) is None


def test_concurrent_reservations_share_the_cap_and_reconcile_to_actual_cost():
    budget = DailyBudget(cap_usd=1.0)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(budget.reserve, [0.6, 0.6]))
    [reserved] = [result for result in results if result is not None]
    assert budget.spent() == pytest.approx(0.6)
    budget.charge(0.2, reservation=reserved)
    assert budget.spent() == pytest.approx(0.2)
    assert budget.reserve(0.8) is not None
    assert budget.reserve(0.01) is None


def test_settlement_uses_the_day_of_admission():
    day = [date(2026, 11, 18)]
    budget = DailyBudget(cap_usd=1.0, today=lambda: day[0])
    reservation = budget.reserve(0.5)
    day[0] = date(2026, 11, 19)
    budget.charge(0.8, reservation=reservation)
    assert budget.spent() == 0


@pytest.fixture
def spent(monkeypatch):
    budget = DailyBudget(cap_usd=1.0)
    budget.charge(1.0)
    for module in ("app.platform.llm.openai_compatible", "app.modules.learning.application.agent.voice",
                   "app.modules.learning.infrastructure.speech.azure_pronunciation",
                   "app.modules.learning.infrastructure.speech.azure_tts"):
        monkeypatch.setattr(f"{module}.daily_budget", lambda: budget)
    return budget


def test_a_text_or_tool_call_is_refused_before_it_is_sent(spent):
    from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider
    provider = OpenAICompatibleLLMProvider.__new__(OpenAICompatibleLLMProvider)
    provider.provider_name, provider.model_name, provider._require_supported_parameters = "p", "gemini-3.5-flash-lite", False
    provider.client = Mock()
    with pytest.raises(LLMProviderError) as refused:
        provider.generate_with_tools([{"role": "user", "content": "hi"}], [])
    assert refused.value.category == LLMProviderFailureCategory.BUDGET_REFUSED
    provider.client.chat.completions.create.assert_not_called()


def test_a_charged_call_counts_its_tokens(monkeypatch):
    from app.platform.llm.openai_compatible import _log_usage
    budget = DailyBudget(cap_usd=5.0)
    monkeypatch.setattr("app.platform.llm.openai_compatible.daily_budget", lambda: budget)
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=100_000,
                                                     completion_tokens_details=SimpleNamespace(reasoning_tokens=100_000)))
    _log_usage(response, provider=SimpleNamespace(provider_name="p", model_name="gemini-3.5-flash-lite"),
               response_model=SimpleNamespace(__name__="R"))
    assert budget.spent() == pytest.approx(0.30 + 0.50)


def test_azure_scoring_and_speech_stop_when_the_budget_is_used_up(spent):
    from app.modules.learning.application.agent.ports import SpeechSynthesisUnavailable
    from app.modules.learning.application.speaking_ports import SpeechProviderFailure
    from app.modules.learning.domain.speech_audio import SpeechAudio
    from app.modules.learning.infrastructure.speech.azure_pronunciation import AzurePronunciationAssessor
    from app.modules.learning.infrastructure.speech.azure_tts import AzureSpeechSynthesizer
    client = Mock()
    assessor = AzurePronunciationAssessor(key="k", region="eastus", client=client)
    with pytest.raises(SpeechProviderFailure) as refused:
        assessor.assess(SpeechAudio(b"\x00\x00" * 16000), reference_text="hello", language_code="en")
    assert refused.value.category == "budget"
    synthesizer = AzureSpeechSynthesizer.__new__(AzureSpeechSynthesizer)
    synthesizer._voices, synthesizer._client = {"en": ("en-US", "en-US-AvaNeural")}, client
    with pytest.raises(SpeechSynthesisUnavailable):
        synthesizer.synthesize("Hello there", language_code="en")
    client.post.assert_not_called()


def test_a_live_conversation_is_refused_before_it_takes_a_slot(spent):
    from tests.learning.test_realtime_companion import FakeChannel, auth, service, start
    relay = service()
    relay.gate = Mock(wraps=relay.gate)
    channel = FakeChannel([auth(), start()])
    asyncio.run(relay.run(channel))
    assert any(message.get("code") == "realtime_limit" for message in channel.json) or channel.closed == 4429
    relay.gate.acquire.assert_not_called()
