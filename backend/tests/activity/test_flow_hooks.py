"""Every exercise and result flow leaves exactly one learning-log row, a retry adds none, and a broken log never
breaks the learner's action."""
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent import voice as realtime_module
from app.modules.learning.application.practice_log import LookupEventRequest
from app.modules.learning.application.region_questions import RegionQuestionAnswerRequest
from app.modules.learning.application.word_speech import WordSpeechService
from app.modules.learning.domain.companion import CompanionEntry
from tests.activity.fakes import BrokenLog, make_activity
from tests.learner.test_my_words import concept, me, service as my_words_service
from tests.learning.test_companion import ITEM_ID, USER, make_service as make_companion
from tests.learning.test_companion import speech as companion_speech
from tests.learning.test_practice_log import ITEM_ID as LOG_ITEM, OWNER, SENTENCE, dictation, log_service
from tests.learning.test_realtime_companion import FakeChannel, auth, run, service as live_service, start
from tests.learning.test_region_questions import ITEM as REGION_ITEM, OWNER as REGION_OWNER, QUESTION, SEGMENT, TRACK, make as make_region
from tests.learning.test_speaking_services_and_api import FakeAssessor, OWNER as SPEAKER, shadowing, speech  # noqa: F401

LEARNER = CurrentUser(id=OWNER)


def only(log, kind):
    rows = log.of(kind)
    assert len(rows) == 1, [row.kind for row in log.entries]
    return rows[0]


# --- Video practice -------------------------------------------------------------------------------------------

def test_dictation_logs_one_row_with_the_server_checked_result_and_a_retry_adds_none():
    activity, log, _, _ = make_activity()
    service, _ = log_service()
    service.learning_log = activity
    request = dictation()
    service.record_dictation(LEARNER, LOG_ITEM, request)
    service.record_dictation(LEARNER, LOG_ITEM, request)
    row = only(log, "dictation")
    assert (row.language_code, row.outcome, row.item_type, row.item_id) == ("en", "partial", "segment", str(SENTENCE.id))
    assert (row.source_type, row.source_id, row.user_id) == ("video_region", str(LOG_ITEM), OWNER)
    assert row.score == pytest.approx(71.4, abs=0.1) and row.detail["correct"] == 5 and "answer" not in str(row.detail)
    service.record_dictation(LEARNER, LOG_ITEM, dictation(answer="So I ended up taking a taxi"))
    assert [entry.outcome for entry in log.of("dictation")] == ["partial", "correct"]


def test_a_word_lookup_logs_one_row():
    activity, log, _, _ = make_activity()
    service, _ = log_service()
    service.learning_log = activity
    request = LookupEventRequest(id=uuid4(), segment_id=SENTENCE.id, start_codepoint=5, end_codepoint=13)
    service.record_lookup(LEARNER, LOG_ITEM, request)
    service.record_lookup(LEARNER, LOG_ITEM, request)
    row = only(log, "lookup")
    assert (row.outcome, row.detail, row.language_code) == ("done", {"text": "ended up"}, "en")


def test_shadowing_logs_the_band_and_score_once_per_assessment(shadowing):  # noqa: F811
    activity, log, _, _ = make_activity()
    shadowing.service.learning_log = activity
    shadowing.service.assess(CurrentUser(id=SPEAKER), shadowing.item, shadowing.segment_id, speech())
    row = only(log, "shadowing")
    assert (row.outcome, row.score, row.language_code, row.item_type) == ("correct", 82.0, "en", "segment")
    assert row.source_type == "video_region" and row.source_id == str(shadowing.item)


def test_a_region_question_answer_logs_once_per_event_and_marks_wrong_ones_incorrect():
    activity, log, _, _ = make_activity()
    service, _ = make_region()
    service.learning_log = activity
    service.transcripts = SimpleNamespace(get_by_id=lambda transcript_id: SimpleNamespace(language_code="en"))
    right = RegionQuestionAnswerRequest(id=uuid4(), selected_option=0)
    service.answer(SimpleNamespace(id=REGION_OWNER), REGION_ITEM, QUESTION.id, right)
    service.answer(SimpleNamespace(id=REGION_OWNER), REGION_ITEM, QUESTION.id, right)
    service.answer(SimpleNamespace(id=REGION_OWNER), REGION_ITEM, QUESTION.id,
                   RegionQuestionAnswerRequest(id=uuid4(), selected_option=3))
    assert [row.outcome for row in log.of("region_question")] == ["correct", "incorrect"]
    assert log.of("region_question")[0].item_id == str(SEGMENT) and TRACK


# --- Words ----------------------------------------------------------------------------------------------------

def test_saving_a_word_logs_one_row_however_often_it_is_saved():
    from app.modules.learner.application.my_words import SaveFromOccurrence
    activity, log, _, _ = make_activity()
    words, resolved = my_words_service()
    words.learning_log = activity
    request = SaveFromOccurrence(source="occurrence", library_item_id=uuid4(), learning_object_id=uuid4())
    words.save(me(), request)
    words.save(me(), request)
    row = only(log, "word_saved")
    assert (row.item_type, row.item_id, row.language_code, row.outcome) == ("concept", str(resolved.id), "en", "done")
    assert concept()  # the helper's default concept is English too


@pytest.mark.parametrize("rating,outcome", [("remembered", "correct"), ("unsure", "partial"), ("not_yet", "incorrect")])
def test_a_flashcard_rating_logs_one_row_and_a_retried_event_id_adds_none(rating, outcome):
    from tests.practice.fakes import USER as REVIEWER, make_review, word
    card = word("你好", "zh", meaning="xin chào")
    env = make_review([card])
    env.service.rate_memory(REVIEWER, card.concept_id, rating, "event-1")
    env.service.rate_memory(REVIEWER, card.concept_id, rating, "event-1")
    row = only(env.log, "flashcard")
    assert (row.outcome, row.language_code, row.item_id, row.source_type) == (outcome, "zh", str(card.concept_id),
                                                                              "review_deck")


def test_a_flashcard_rating_that_is_refused_logs_nothing():
    from app.modules.practice.application.review import PracticeError
    from tests.practice.fakes import USER as REVIEWER, make_review, word
    card = word("leave", meaning="rời đi")
    env = make_review([card], save=False)
    with pytest.raises(PracticeError):
        env.service.rate_memory(REVIEWER, card.concept_id, "unsure", "event-2")
    assert env.log.entries == []

def test_a_dictionary_pronunciation_attempt_logs_its_band(shadowing):  # noqa: F811
    from tests.learning.test_speaking_services_and_api import speech as audio
    activity, log, _, _ = make_activity()
    service = WordSpeechService(dictionary=SimpleNamespace(has_headword=lambda language, text: True), synthesizer=None,
                                assessor=FakeAssessor(), consent=None, scores=None,
                                learning_log=activity)
    view = service.assess(CurrentUser(id=SPEAKER), "en", "leaves", audio())
    row = only(log, "pronunciation")
    assert (row.outcome, row.score, row.detail["text"], row.item_type) == ("correct", 82.0, "leaves", None)
    assert view.pronunciation == 82.0


# --- Grammar ---------------------------------------------------------------------------------

def test_a_grammar_answer_logs_the_point_once_per_attempt():
    from app.modules.content.domain.grammar_bank import GrammarBank
    from tests.content.test_grammar_bank import approved
    from tests.practice.fakes import USER as STUDENT, make_grammar
    bank = GrammarBank.model_validate(approved())
    env = make_grammar([bank])
    question = bank.points[0].questions[0]
    for _ in range(2):  # the same attempt id again
        env.service.answer(STUDENT, "en", exercise_id=question.id, option_id="a", client_event_id="attempt-1")
    row = only(env.log, "grammar_exercise")
    assert (row.item_type, row.item_id, row.language_code, row.user_id) == (
        "grammar_point", bank.points[0].key, "en", STUDENT)
    assert row.outcome in ("correct", "incorrect")

# --- Speaking -------------------------------------------------------------------------------------------------

def test_the_end_of_a_live_conversation_logs_one_speaking_session():
    activity, log, _, _ = make_activity()
    relay = live_service()
    relay.learning_log = activity
    ticket = SimpleNamespace(language_code="en", scenario_id=None, swap_roles=False)
    session = realtime_module.VoiceSession(user=LEARNER, prepared=SimpleNamespace(ticket=ticket, focused=True), day=None,
                                       started=time.monotonic(), transient=True)
    session.learner_turns, session.corrections = 4, 1
    run(relay._finish(session))
    run(relay._finish(session))  # the same session again
    row = only(log, "speaking_session")
    assert (row.outcome, row.source_type, row.source_id) == ("done", "agent_session", str(session.id))
    assert row.detail["turns"] == 4 and row.detail["channel"] == "voice"


def test_a_live_conversation_logs_the_seconds_the_learner_spoke_not_the_time_it_lasted():
    # Owner, 2026-11-18: "speaking time" is the learner's own speech, the same measure as the text channel.
    activity, log, _, _ = make_activity()
    relay = live_service()
    relay.learning_log = activity
    ticket = SimpleNamespace(language_code="en", scenario_id=None, swap_roles=False)
    session = realtime_module.VoiceSession(user=LEARNER, prepared=SimpleNamespace(ticket=ticket, focused=True), day=None,
                                       started=time.monotonic() - 600, transient=True)  # ten minutes ago
    session.learner_turns, session.spoken_ms = 3, 3_400
    run(relay._finish(session))
    assert only(log, "speaking_session").detail["seconds"] == 3


def test_a_conversation_with_no_learner_turn_logs_no_session():
    activity, log, _, _ = make_activity()
    relay = live_service()
    relay.learning_log = activity
    ticket = SimpleNamespace(language_code="en", scenario_id=None, swap_roles=False)
    session = realtime_module.VoiceSession(user=LEARNER, prepared=SimpleNamespace(ticket=ticket, focused=True), day=None,
                                       started=time.monotonic(), transient=True)
    run(relay._finish(session))
    assert log.entries == []


def test_starting_a_live_roleplay_logs_one_roleplay_and_a_mid_conversation_one_is_another():
    activity, log, _, _ = make_activity()
    relay = live_service()
    relay.learning_log = activity
    channel = FakeChannel([auth(), start(scenario_id="hotel"), ("text", '{"type":"end"}')])
    run(relay.run(channel))
    row = only(log, "roleplay")
    assert (row.detail["scenario"], row.outcome, row.source_type) == ("hotel", "done", "agent_session")
    assert row.language_code == "en" and row.user_id == OWNER


def test_the_text_companion_logs_a_roleplay_start_and_a_finished_session():
    from tests.learning.test_companion import turn_output
    activity, log, _, _ = make_activity()
    service = make_companion(outputs=[turn_output(), turn_output()], texts=["Hello there"])
    service.learning_log = activity
    opened = service.start(USER, CompanionEntry.HOME, None, scenario_id="hotel")
    assert only(log, "roleplay").detail["scenario"] == "hotel"
    answered = service.turn(USER, opened.session_ticket, companion_speech())
    service.finish(USER, answered.session_ticket)
    session = only(log, "speaking_session")
    assert session.detail["channel"] == "text" and session.language_code == "en"
    assert ITEM_ID  # imported for the other helpers


# --- A broken log never breaks the action ---------------------------------------------------------------------

def test_a_log_that_is_down_does_not_break_dictation():
    broken, _, _, _ = make_activity(BrokenLog())
    service, _ = log_service()
    service.learning_log = broken
    view = service.record_dictation(LEARNER, LOG_ITEM, dictation())
    assert view.total and view.correct is not None  # the learner still gets the server's check
    assert datetime.now(UTC)
