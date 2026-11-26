"""FR-3.6: what the agent learns about a learner is closed codes only: interests, goals, error kinds,
speaking pace and turn length. Nothing is kept without the stored voice consent, and never any text."""
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.learner.application.agent_signals import AgentSignalsService
from app.modules.learner.contracts import SIGNAL_CODES
from app.modules.learner.domain.agent_signals import AgentConsent, PersonalizationSignal, SignalKind
from app.modules.learning.application.speaking_signals import pace_code, turn_length_code, turn_units
from app.modules.learning.domain.realtime import valid_signal
from tests.learning.speaking_fixtures import pcm_silence, pcm_tone
from tests.learning.test_companion import OWNER
from tests.learning.test_realtime_companion import (
    FakeChannel, FakeVoice, ToolCall, TranscriptPiece, TurnComplete, auth, service as relay_service, start,
)


class FakeSignals:
    def __init__(self):
        self.calls = []

    def record(self, user_id, *, language_code, signals):
        self.calls.append((user_id, language_code, list(signals)))

    def recurring(self, user_id, *, language_code):
        return []

    @property
    def recorded(self):
        return {(kind, code) for _, _, signals in self.calls for kind, code in signals}


def run_session(turns, *, tools=(), signals=None):
    """``turns``: (audio_pcm | None, learner_text); ``tools``: tool calls made before the session ends."""
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.signals = signals if signals is not None else FakeSignals()
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for pcm, text in turns:
            if pcm:
                for offset in range(0, len(pcm), 32_000):
                    await channel.inbound.put(("bytes", pcm[offset:offset + 32_000]))
                await asyncio.sleep(0.02)
            for event in (TranscriptPiece("learner", text), TranscriptPiece("companion", "I see. And then?"),
                          TurnComplete()):
                await voice.connection.events_queue.put(event)
            await asyncio.sleep(0.04)
        for index, (name, args) in enumerate(tools):
            await voice.connection.events_queue.put(ToolCall(str(index), name, args))
            await asyncio.sleep(0.03)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    return relay.signals, channel, voice


# --- Pure pieces -------------------------------------------------------------------------------

def test_a_turn_is_measured_in_words_or_characters():
    assert turn_units("I like to travel by train.", "en") == 6
    assert turn_units("我喜欢坐火车旅行。", "zh") == 8
    assert turn_units("", "en") == 0


@pytest.mark.parametrize("units, ms, language, code", [
    (30, 30_000, "en", "slow"), (60, 30_000, "en", "steady"), (90, 30_000, "en", "fast"),
    (50, 30_000, "zh", "slow"), (90, 30_000, "zh", "steady"), (150, 30_000, "zh", "fast"),
])
def test_pace_is_slow_steady_or_fast_for_the_language(units, ms, language, code):
    assert pace_code(units, ms, language) == code


def test_pace_needs_enough_speech_to_mean_anything():
    assert pace_code(5, 1000, "en") is None


@pytest.mark.parametrize("sizes, language, code", [
    ([3, 4], "en", "short"), ([8, 10], "en", "medium"), ([20, 25], "en", "long"),
    ([4, 5], "zh", "short"), ([12, 15], "zh", "medium"), ([30, 40], "zh", "long"), ([9], "en", None),
])
def test_turn_length_is_the_average_size_of_the_learners_turns(sizes, language, code):
    assert turn_length_code(sizes, language) == code


def test_a_signal_must_be_a_closed_code_of_its_kind():
    assert valid_signal("topic", "travel") == ("topic", "travel")
    assert valid_signal("goal", "exam") == ("goal", "exam")
    for kind, code in [("topic", "Hà Nội"), ("topic", "my boss Lan"), ("goal", "travel2"), ("pace", "travel"),
                       ("topic", None), ("secret", "travel")]:
        assert valid_signal(kind, code) is None
    assert set(SIGNAL_CODES) == {"topic", "goal", "error_type", "pace", "turn_length"}


# --- In the conversation -----------------------------------------------------------------------

def test_what_the_learner_says_they_like_and_want_is_kept_as_codes_when_the_model_notes_it():
    signals, _, voice = run_session([(None, "I love to travel because I want to pass my exam.")], tools=[
        ("note_interest", {"topic": "travel"}), ("note_goal", {"goal": "exam"}),
        ("note_interest", {"topic": "travel"})])
    assert ("topic", "travel") in signals.recorded and ("goal", "exam") in signals.recorded
    assert [signal for _, _, items in signals.calls for signal in items].count(("topic", "travel")) == 1
    assert [response for _, _, response in voice.connection.tool_responses] == [{"noted": True}] * 3


def test_a_made_up_interest_or_a_name_is_not_kept_and_the_model_is_told_so():
    signals, _, voice = run_session([(None, "My friend Lan lives in Hà Nội.")], tools=[
        ("note_interest", {"topic": "Hà Nội"}), ("note_goal", {"goal": "visit Lan"})])
    assert signals.recorded == set()
    assert [response for _, _, response in voice.connection.tool_responses] == [{"noted": False}] * 2


def test_the_kinds_of_signal_never_carry_the_learners_words():
    signals, channel, _ = run_session([(None, "I want to travel to Hà Nội with Lan.")],
                                      tools=[("note_goal", {"goal": "travel"})])
    assert "Lan" not in str(signals.calls) and "Hà" not in str(signals.calls)
    assert "Lan" not in str(channel.json[-1])


def test_pace_and_turn_length_come_from_how_the_learner_spoke():
    long_turn = "word " * 40
    speech = pcm_silence(300) + pcm_tone(12_000) + pcm_silence(300)
    signals, _, _ = run_session([(speech, long_turn), (speech, long_turn)])
    assert ("turn_length", "long") in signals.recorded
    assert ("pace", "steady") in signals.recorded or ("pace", "fast") in signals.recorded


def test_a_single_short_exchange_says_nothing_about_pace_or_turn_length():
    signals, _, _ = run_session([(None, "Yes.")])
    assert not {kind for kind, _ in signals.recorded} & {"pace", "turn_length"}


def test_without_a_granted_consent_nothing_at_all_is_noted():
    class Denied:
        def has_consent(self, user_id):
            return False
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.consent, relay.signals = Denied(), FakeSignals()
    channel = FakeChannel([auth(), start()])
    asyncio.run(relay.run(channel))
    assert relay.signals.calls == [] and voice.opened == []


def test_a_consent_revoked_before_the_end_keeps_nothing():
    class Flip:
        def __init__(self):
            self.answers = [True, False]

        def has_consent(self, user_id):
            return self.answers.pop(0) if self.answers else False
    voice = FakeVoice()
    relay = relay_service(voice=voice)
    relay.consent, relay.signals = Flip(), FakeSignals()
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(ToolCall("1", "note_interest", {"topic": "travel"}))
        await asyncio.sleep(0.03)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    assert relay.signals.calls == []


# --- The adapter to the stored signals ---------------------------------------------------------

class _Consents:
    def __init__(self, granted=True):
        self.row = AgentConsent(user_id=OWNER, voice_consent=granted, decided_at=datetime.now(UTC))

    def get(self, user_id):
        return self.row if user_id == OWNER else None


class _Store:
    def __init__(self):
        self.rows = []

    def list_all(self, user_id):
        return [row for row in self.rows if row.user_id == user_id]

    def record(self, user_id, *, language_code, kind, code, replace_kind):
        if replace_kind:
            self.rows = [row for row in self.rows if not (row.kind == kind and row.language_code == language_code)]
        self.rows.append(PersonalizationSignal(id=uuid4(), user_id=user_id, language_code=language_code, kind=kind,
                                               code=code))


def test_the_adapter_stores_every_kind_under_consent_and_drops_what_is_not_a_closed_code():
    from app.bootstrap.wiring.agent import PersonalizationSignals
    adapter = PersonalizationSignals(AgentSignalsService(consents=_Consents(True), signals=_Store()))
    adapter.record(OWNER, language_code="en", signals=[("topic", "food"), ("goal", "exam"), ("error_type", "articles"),
                                                       ("pace", "slow"), ("turn_length", "short"), ("topic", "Lan")])
    stored = {(row.kind.value, row.code) for row in adapter.signals.store.rows}
    assert stored == {("topic", "food"), ("goal", "exam"), ("error_type", "articles"), ("pace", "slow"),
                      ("turn_length", "short")}
    adapter.record(OWNER, language_code="en", signals=[("pace", "fast")])
    assert [row.code for row in adapter.signals.store.rows if row.kind == SignalKind.PACE] == ["fast"]
