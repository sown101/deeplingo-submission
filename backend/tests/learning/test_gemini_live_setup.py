"""The Live session setup keeps per-turn cost bounded and hands the end-of-turn silence to the provider."""
import asyncio
import json

from app.modules.learning.infrastructure.speech import gemini_live
from app.platform.config import Settings


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        return json.dumps({"setupComplete": {}})

    async def close(self):
        pass


def test_setup_bounds_the_context_window_and_passes_the_silence(monkeypatch):
    socket = FakeSocket()

    async def fake_connect(*args, **kwargs):
        return socket

    monkeypatch.setattr(gemini_live, "connect", fake_connect)
    voice = gemini_live.GeminiLiveVoice(project="p", region="us-central1", model="m", token_provider=lambda _: "token")
    asyncio.run(voice.open(language_code="en", instruction="hi", silence_ms=1000))

    setup = socket.sent[0]["setup"]
    window = setup["contextWindowCompression"]
    assert window == {"triggerTokens": gemini_live.CONTEXT_TRIGGER_TOKENS,
                      "slidingWindow": {"targetTokens": gemini_live.CONTEXT_TARGET_TOKENS}}
    assert 5000 <= gemini_live.CONTEXT_TRIGGER_TOKENS and gemini_live.CONTEXT_TARGET_TOKENS < gemini_live.CONTEXT_TRIGGER_TOKENS
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] == 1000


def test_end_of_turn_silence_defaults_to_one_second():
    assert Settings.model_fields["COMPANION_REALTIME_SILENCE_MS"].default == 1000
