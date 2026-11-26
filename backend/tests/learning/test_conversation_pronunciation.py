"""FR-3.8: pronunciation feedback in the conversation, from a fake Azure.

The learner's audio of each turn is kept in memory only, scored once against the words the learner
said, and dropped. The result is practice feedback: weak words in the end-of-session summary, never
a score, never the usage ladder.
"""
import asyncio

import pytest

from app.modules.learning.application.agent import voice as realtime_module
from app.modules.learning.application.conversation_pronunciation import (
    MAX_WEAK_WORDS,
    TurnAudioBuffer,
    weak_words,
)
from app.modules.learning.application.speaking_ports import NoSpeechDetected, SpeechProviderFailure
from app.modules.learning.domain.speaking import (
    PronunciationErrorType as Error,
    PronunciationResult,
    PronunciationScores,
    PronunciationWord,
)
from app.modules.learning.domain.speech_audio import SpeechAudio, trim_to_speech
from tests.learning.speaking_fixtures import pcm_silence, pcm_tone
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)


def word(text, accuracy, error=Error.NONE):
    return PronunciationWord(word=text, accuracy=accuracy, error_type=error)


def result(*words):
    return PronunciationResult(recognized_text="x", scores=PronunciationScores(80, 80, 80, 80), words=tuple(words))


class FakeAssessor:
    provider_name = "fake"

    def __init__(self, outcome=None, languages=("en",)):
        self.outcome = outcome or result(word("travel", 40, Error.MISPRONUNCIATION), word("train", 0, Error.OMISSION),
                                         word("like", 95))
        self.languages, self.calls = languages, []

    def supports(self, language_code):
        return language_code in self.languages

    def assess(self, audio, *, reference_text, language_code):
        self.calls.append((reference_text, audio.duration_ms, language_code))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def tone(ms):
    return pcm_silence(300) + pcm_tone(ms) + pcm_silence(300)


class Denied:
    def has_consent(self, user_id):
        return False


def run_session(turns, *, assessor=None, consented=True):
    """``turns``: (audio_pcm, learner_text) pairs; the companion answers after each one."""
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.pronunciation = assessor if assessor is not None else FakeAssessor()
    if not consented:
        relay.consent = Denied()
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for pcm, text in turns:
            for offset in range(0, len(pcm), 32_000):
                await channel.inbound.put(("bytes", pcm[offset:offset + 32_000]))
            await asyncio.sleep(0.02)
            for event in (TranscriptPiece("learner", text), TranscriptPiece("companion", "Nice. And you?"),
                          TurnComplete()):
                await voice.connection.events_queue.put(event)
            await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    return relay.pronunciation, channel


# --- Pure pieces -------------------------------------------------------------------------------

def test_the_buffer_hands_over_a_turn_once_and_stays_bounded():
    buffer = TurnAudioBuffer(max_bytes=10)
    buffer.add(b"a" * 6)
    buffer.add(b"b" * 6)
    data, truncated = buffer.take()
    assert data == b"a" * 4 + b"b" * 6 and truncated
    assert buffer.take() == (b"", False)


def test_only_the_spoken_part_is_kept_and_silence_alone_is_nothing():
    clip = trim_to_speech(SpeechAudio(pcm_silence(2000) + pcm_tone(1000) + pcm_silence(2000)))
    assert clip is not None and 1000 <= clip.duration_ms <= 1500
    assert trim_to_speech(SpeechAudio(pcm_silence(3000))) is None


def test_weak_words_are_real_mispronunciations_only_worst_first_and_limited():
    outcome = result(word("travel", 40, Error.MISPRONUNCIATION), word("Train", 55), word("train", 30),
                     word("said", 0, Error.OMISSION), word("uh", 0, Error.INSERTION), word("like", 95),
                     *[word(f"w{index}", 50 + index, Error.MISPRONUNCIATION) for index in range(8)])
    found = weak_words([outcome])
    assert found[:2] == ["train", "travel"] and len(found) == MAX_WEAK_WORDS
    assert "said" not in found and "uh" not in found and "like" not in found


# --- In the conversation -----------------------------------------------------------------------

def test_each_turn_is_scored_once_against_its_own_words_and_audio():
    assessor, channel = run_session([(tone(1000), "I like to travel by train."), (tone(2000), "It is fun.")])
    assert [call[0] for call in assessor.calls] == ["I like to travel by train.", "It is fun."]
    first, second = (call[1] for call in assessor.calls)
    assert 1000 <= first <= 1500 and 2000 <= second <= 2500
    assert all(call[2] == "en" for call in assessor.calls)


def test_the_summary_names_weak_words_without_any_score():
    _, channel = run_session([(tone(1000), "I like to travel by train.")])
    summary = channel.json[-1]["summary"]
    assert summary["weak_words"] == ["travel"]
    assert not {"score", "scores", "pronunciation", "accuracy", "level", "grade"} & set(summary)
    assert "80" not in str(channel.json[-1])


def test_without_the_learners_consent_there_is_no_voice_session_so_nothing_is_buffered_or_sent():
    assessor, channel = run_session([(tone(1000), "I like to travel.")], consented=False)
    assert assessor.calls == [] and channel.json[-1]["code"] == "voice_consent_required"


def test_a_language_azure_cannot_score_is_skipped():
    assessor, _ = run_session([(tone(1000), "I like to travel.")], assessor=FakeAssessor(languages=("zh",)))
    assert assessor.calls == []


def test_silence_too_long_a_turn_or_too_many_words_are_not_scored():
    assessor, _ = run_session([
        (pcm_silence(3000), "Hmm."),
        (pcm_tone(31_000), "I talk for a very long time."),
        (tone(1000), "word " * 80),
    ])
    assert assessor.calls == []


@pytest.mark.parametrize("failure", [NoSpeechDetected(), SpeechProviderFailure("busy"), RuntimeError("boom")])
def test_a_failing_provider_never_breaks_or_marks_the_learner(failure):
    _, channel = run_session([(tone(1000), "I like to travel.")], assessor=FakeAssessor(failure))
    assert channel.json[-1]["type"] == "ended" and "weak_words" not in channel.json[-1]["summary"]


def test_the_number_of_scored_turns_is_capped(monkeypatch):
    monkeypatch.setattr(realtime_module, "MAX_SCORED_TURNS", 2)
    assessor, _ = run_session([(tone(800), f"Turn number {n}.") for n in range(4)])
    assert len(assessor.calls) == 2


def test_nothing_of_the_audio_reaches_the_analysis_or_the_ended_message():
    from unittest.mock import Mock
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.pronunciation = FakeAssessor()
    relay.session_events = Mock()
    relay.session_events.submit.return_value = {"session_id": "s", "status": "queued"}
    relay.setup.target_catalog = Mock()
    relay.setup.target_catalog.saved_items.return_value = []
    run = FakeChannel([auth(), start(), ("bytes", tone(1000))])

    async def scenario():
        task = asyncio.create_task(relay.run(run))
        await asyncio.sleep(0.05)
        for event in (TranscriptPiece("learner", "I like to travel."), TurnComplete()):
            await voice.connection.events_queue.put(event)
        await asyncio.sleep(0.05)
        await run.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert not any(isinstance(value, (bytes, bytearray)) for message in run.json for value in message.values())


def test_each_scored_turn_shows_one_overall_number_and_its_weak_words_on_screen():
    _, channel = run_session([(tone(1000), "I like to travel by train."), (tone(1000), "It is fun.")])
    shown = [message for message in channel.json if message["type"] == "pronunciation"]
    assert shown == [{"type": "pronunciation", "turn": 1, "overall": 80, "weak_words": ["travel"]},
                     {"type": "pronunciation", "turn": 2, "overall": 80, "weak_words": ["travel"]}]


def test_a_turn_that_cannot_be_scored_shows_nothing():
    _, channel = run_session([(tone(1000), "I like to travel.")], assessor=FakeAssessor(SpeechProviderFailure("busy")))
    assert "pronunciation" not in channel.types()
