import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.modules.learning.domain.realtime import transcript_breach
from app.modules.learning.domain.companion import CompanionEntry
from tests.learning.test_companion import ITEM_ID, USER
from tests.learning.test_realtime_companion import (
    FakeChannel, TranscriptPiece, TurnComplete, auth, service, start,
)


@pytest.mark.parametrize("text", ["。", "…", "？！", "123", "2026。", "!? "])
def test_nonverbal_chinese_transcription_is_not_a_wrong_language(text):
    assert transcript_breach(text, "zh") is None


@pytest.mark.parametrize("text,language,breach", [
    ("Hello!", "zh", "wrong_language"),
    ("你好", "en", "wrong_language"),
    ("Bạn hãy thử lại", "zh", "support_language"),
    ("línjū", "zh", "support_language"),
    ("10/10", "zh", "grading_claim"),
    ("你得了满分！", "zh", "grading_claim"),
])
def test_nonverbal_fix_keeps_language_and_grading_rejections(text, language, breach):
    assert transcript_breach(text, language) == breach


def test_chinese_hint_control_turn_does_not_end_selected_word_conversation():
    async def scenario():
        relay = service()
        prepared = relay.setup.prepare(USER, CompanionEntry.VIDEO, ITEM_ID)
        prepared = replace(prepared, ticket=replace(prepared.ticket, language_code="zh"))
        relay.setup.prepare = Mock(return_value=replace(prepared, focused=True))
        channel = FakeChannel([auth(), start()])
        task = asyncio.create_task(relay.run(channel))
        try:
            for _ in range(100):
                if channel.json:
                    break
                await asyncio.sleep(.01)
            assert channel.json[0]["type"] == "ready"
            await channel.inbound.put(("text", json.dumps({"type": "help"})))
            for _ in range(100):
                if relay.voice.connection.texts:
                    break
                await asyncio.sleep(.01)
            cue = relay.voice.connection.texts[0]
            assert "selected words" in cue
            assert all(item.text in cue for item in prepared.ticket.items)
            for event in (TranscriptPiece("companion", "你好！"), TurnComplete(),
                          TranscriptPiece("companion", "。"), TurnComplete()):
                await relay.voice.connection.events_queue.put(event)
            for _ in range(100):
                if channel.types().count("turn_complete") == 2:
                    break
                await asyncio.sleep(.01)
            assert channel.types().count("turn_complete") == 2
            assert "ended" not in channel.types()
            await channel.inbound.put(("text", json.dumps({"type": "end"})))
            await asyncio.wait_for(task, 2)
            assert channel.json[-1]["reason"] == "learner_ended"
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
