"""The fallback obeys the same consent and evidence rules as live voice; no providers."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import CompanionEntry
from tests.learning.test_companion import FLY, ITEM_ID, USER, make_service, speech, turn_output
from tests.learning.test_conversation_pronunciation import FakeAssessor


def test_revoked_consent_blocks_before_transcription_or_model_calls():
    service = make_service()
    service.consent = SimpleNamespace(has_consent=lambda _: False)
    with pytest.raises(SpeakingPracticeError) as error:
        service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert error.value.code == "voice_consent_required"
    assert not service.model.prompts


def test_consent_revoked_after_start_blocks_the_next_audio_turn():
    service = make_service(texts=["I like flying"])
    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    service.consent = SimpleNamespace(has_consent=lambda _: False)
    with pytest.raises(SpeakingPracticeError) as error:
        service.turn(USER, opened.session_ticket, speech())
    assert error.value.code == "voice_consent_required"
    assert service.transcriber.texts == ["I like flying"]


def test_finish_submits_owned_word_use_with_prior_support_and_pronunciation():
    service = make_service(outputs=[turn_output(), turn_output()], texts=["I enjoy flying every summer"])
    service.session_events = Mock()
    service.session_events.submit.side_effect = lambda data: {"session_id": str(data.id), "status": "queued"}
    service.pronunciation = FakeAssessor()
    service.target_catalog = SimpleNamespace(saved_items=lambda *args, **kwargs: [FLY])
    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    answered = service.turn(USER, opened.session_ticket, speech())
    assert not service.session_events.submit.called
    closed = service.finish(USER, answered.session_ticket)
    data = service.session_events.submit.call_args.args[0]
    assert data.user_id == USER.id and data.library_item_id == ITEM_ID
    assert data.turns[0].text == "I enjoy flying every summer"
    assert data.targets[0].text == "fly"
    assert data.targets[0].concept_id in data.turns[0].assisted_ids
    assert closed.analysis["status"] == "queued"
    assert closed.weak_words == ["travel"]
    with pytest.raises(SpeakingPracticeError):
        service.finish(USER, answered.session_ticket)
    assert service.session_events.submit.call_count == 1


def test_revoking_before_finish_drops_learning_and_pronunciation_results():
    service = make_service(outputs=[turn_output(), turn_output()], texts=["I enjoy flying"])
    service.session_events = Mock()
    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    answered = service.turn(USER, opened.session_ticket, speech())
    service.consent = SimpleNamespace(has_consent=lambda _: False)
    closed = service.finish(USER, answered.session_ticket)
    assert closed.analysis is None and closed.weak_words == []
    assert not service.session_events.submit.called


def test_pronunciation_outage_does_not_prevent_the_conversation_or_grant_learning_credit():
    service = make_service(outputs=[turn_output(), turn_output()], texts=["I enjoy flying"])
    service.pronunciation = FakeAssessor(outcome=RuntimeError("provider unavailable"))
    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    answered = service.turn(USER, opened.session_ticket, speech())
    assert answered.learner_transcript == "I enjoy flying"
    closed = service.finish(USER, answered.session_ticket)
    assert closed.weak_words == []
    assert closed.analysis["status"] == "unavailable"


def test_only_saved_words_are_submitted_and_later_support_does_not_change_earlier_turns():
    service = make_service(outputs=[turn_output(reply="Tell me about your trip."), turn_output()], texts=["I enjoy flying"])
    service.session_events = Mock()
    service.session_events.submit.return_value = {"session_id": "unused", "status": "queued"}
    service.target_catalog = SimpleNamespace(saved_items=lambda *args, **kwargs: [FLY])
    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    answered = service.turn(USER, opened.session_ticket, speech())
    service.finish(USER, answered.session_ticket)
    data = service.session_events.submit.call_args.args[0]
    assert data.turns[0].assisted_ids == []
    assert len(data.targets) == 1 and str(data.targets[0].concept_id) == FLY.concept_id


@pytest.mark.parametrize("has_voice_consent", [False, True])
def test_text_only_never_uses_speech_or_memory_and_always_refuses_audio(has_voice_consent):
    from app.modules.learning.application.agent.context import ContextBuilder

    service = make_service(outputs=[turn_output(), turn_output()])
    service.consent = Mock()
    service.consent.has_consent.return_value = has_voice_consent
    service.transcriber = None
    service.memory = Mock()
    service.context_builder = ContextBuilder(None, memory=service.memory)
    service.learning_log = Mock()
    service.session_events = Mock()

    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID, text_only=True)
    assert opened.audio is None and opened.audio_status == "unavailable"
    assert service.load(USER, opened.session_ticket).text_only
    with pytest.raises(SpeakingPracticeError) as error:
        service.turn(USER, opened.session_ticket, speech())
    assert error.value.code == "companion_text_only"

    answered = service.turn(USER, opened.session_ticket, text="I enjoy flying", speak=False)
    assert answered.learner_transcript == "I enjoy flying"
    assert list(service.speak_parts(answered)) == []
    closed = service.finish(USER, answered.session_ticket)
    assert closed.analysis is None and closed.weak_words == []
    assert not service.synthesizer.calls
    assert not service.consent.mock_calls
    assert not service.memory.mock_calls
    assert not service.learning_log.mock_calls
    service.session_events.submit.assert_not_called()


def test_a_typed_reply_in_a_microphone_session_is_never_speaking_evidence():
    service = make_service(outputs=[turn_output(), turn_output()])
    service.session_events = Mock()
    service.target_catalog = SimpleNamespace(saved_items=lambda *args, **kwargs: [FLY])
    opened = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    answered = service.turn(USER, opened.session_ticket, text="I enjoy flying every summer")

    assert service.finish(USER, answered.session_ticket).analysis is None
    service.session_events.submit.assert_not_called()
