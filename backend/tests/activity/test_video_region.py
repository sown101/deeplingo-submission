"""Phase 3: bilingual subtitles, practice scoped to a study region, and the region result card."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.content import get_segment_translation_service, get_word_lookup_limiter
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.speaking import get_practice_log_limiter, get_practice_log_service, get_region_result_service
from app.kernel.region_ids import region_id, split_region_id
from app.main import app
from app.modules.activity.contracts import ActivityEntry, region_result
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.segment_translation import (
    CHUNK_SENTENCES,
    SegmentTranslationService,
    TranslationAnswer,
)
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.my_words import SaveFromOccurrence
from app.modules.learning.application.practice_log import DictationEventRequest, LookupEventRequest, PracticeLogError
from app.modules.learning.application.region_questions import CurrentRegionQuestionSet, RegionQuestionAnswerRequest
from app.modules.learning.application.region_result import RegionResultService
from app.platform.rate_limit import SlidingWindowLimiter
from tests.activity.fakes import make_activity
from tests.learner.test_my_words import me, service as my_words_service
from tests.learning.test_practice_log import ITEM_ID, OWNER, SENTENCE, log_service
from tests.learning.test_region_questions import ITEM as Q_ITEM, OWNER as Q_OWNER, QUESTION, SEGMENT, TRACK as Q_TRACK
from tests.learning.test_region_questions import make as make_questions
from tests.learning.test_speaking_services_and_api import OWNER as SPEAKER, shadowing, speech  # noqa: F401

LEARNER = CurrentUser(id=OWNER)
AUTH = {"Authorization": "Bearer owner.test.jwt"}


def sign_in(user):
    verifier = Mock()
    verifier.verify.side_effect = lambda token: user
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier


# --- Region ids -----------------------------------------------------------------------------------------------

def test_a_region_id_round_trips_and_rejects_anything_else():
    start, end = uuid4(), uuid4()
    assert split_region_id(region_id(start, end)) == (start, end)
    for bad in ("", "x", f"{start}", f"{start}_{end}_{start}", f"{start}_nope", f"{str(start).upper()}_{end}"):
        assert split_region_id(bad) is None


# --- Bilingual subtitles --------------------------------------------------------------------------------------

class Translations:
    """The shared translation rows, keyed like the table: (segment, language)."""

    def __init__(self):
        self.rows: dict = {}

    def translated_segment_ids(self, segment_ids, language_code):
        return {segment for segment in segment_ids if (segment, language_code) in self.rows}

    def upsert_many(self, rows):
        for row in rows:
            self.rows[(UUID(row["transcript_segment_id"]), row["language_code"])] = row
        return rows


def numbered(prompt, model, **kwargs):
    return TranslationAnswer.model_validate({"translations": [
        {"n": number, "text": f"Dòng {number}"} for number in range(1, prompt.count("\n[") + 2)]})


def translation_service(*, count=3, support="vi", language="en", answer=numbered):
    owner, item, video_id, track = uuid4(), uuid4(), uuid4(), uuid4()
    library, videos, transcripts, segments, preferences, provider = (Mock() for _ in range(6))
    library.get_for_user.side_effect = lambda **kw: SimpleNamespace(video_id=video_id) if kw["user_id"] == owner else None
    videos.get_by_id.return_value = SimpleNamespace(id=video_id, processing_status="transcript_ready",
                                                    original_language_code=language)
    transcripts.list_for_video.return_value = [SimpleNamespace(id=track, is_original=True, language_code=language,
                                                               source="caption_track")]
    rows = [SimpleNamespace(id=uuid4(), transcript_id=track, sequence_number=index, text=f"Line {index}.")
            for index in range(1, count + 1)]
    segments.list_for_transcript.return_value = rows
    preferences.get_by_language_for_user.return_value = SimpleNamespace(support_language_code=support) if support else None
    provider.generate_structured.side_effect = answer
    store = Translations()
    service = SegmentTranslationService(library=library, videos=videos, transcripts=transcripts, segments=segments,
                                        preferences=preferences, translations=store, provider=provider)
    return SimpleNamespace(service=service, user=CurrentUser(id=owner), item=item, rows=rows, store=store,
                           provider=provider, preferences=preferences)


def test_the_first_open_translates_into_the_support_language_and_stores_shared_rows():
    source = translation_service()
    view = source.service.ensure(source.user, source.item)
    assert (view.status, view.language_code, view.translated) == ("ready", "vi", 3)
    assert {key[1] for key in source.store.rows} == {"vi"} and len(source.store.rows) == 3
    stored = source.store.rows[(source.rows[1].id, "vi")]
    assert stored["text"] == "Dòng 2" and stored["source"] == "ai" and str(source.user.id) not in str(stored)
    prompt = source.provider.generate_structured.call_args.args[0]
    assert "into vi" in prompt and "[1] Line 1." in prompt


def test_translations_are_cached_so_a_second_learner_with_the_same_pair_costs_no_model_call():
    source = translation_service()
    source.service.ensure(source.user, source.item)
    again = source.service.ensure(source.user, source.item)
    assert (again.status, again.translated) == ("ready", 0)
    assert source.provider.generate_structured.call_count == 1


def test_another_support_language_is_translated_separately():
    source = translation_service()
    source.service.ensure(source.user, source.item)
    source.preferences.get_by_language_for_user.return_value = SimpleNamespace(support_language_code="fr")
    source.service.ensure(source.user, source.item)
    assert {key[1] for key in source.store.rows} == {"vi", "fr"} and source.provider.generate_structured.call_count == 2


def test_a_long_transcript_is_translated_in_chunks_and_only_missing_sentences_are_sent():
    source = translation_service(count=CHUNK_SENTENCES + 5)
    source.store.rows[(source.rows[0].id, "vi")] = {"text": "đã có"}
    view = source.service.ensure(source.user, source.item)
    assert view.translated == CHUNK_SENTENCES + 4 and source.provider.generate_structured.call_count == 2
    assert source.store.rows[(source.rows[0].id, "vi")] == {"text": "đã có"}


def test_no_translation_is_asked_when_the_support_language_is_the_video_language_or_unset():
    for support in ("en", None):
        source = translation_service(support=support)
        assert source.service.ensure(source.user, source.item).status == "not_needed"
        source.provider.generate_structured.assert_not_called()


def test_a_model_failure_or_unusable_answer_is_reported_and_stores_nothing():
    def down(*args, **kwargs):
        raise RuntimeError("down")

    failing = translation_service(answer=down)
    assert failing.service.ensure(failing.user, failing.item).status == "unavailable" and failing.store.rows == {}
    off_range = translation_service(answer=lambda *a, **k: TranslationAnswer.model_validate(
        {"translations": [{"n": 9, "text": "x"}]}))
    assert off_range.service.ensure(off_range.user, off_range.item).status == "unavailable"
    assert off_range.store.rows == {}


def test_a_partial_answer_stores_what_it_has():
    partial = translation_service(answer=lambda *a, **k: TranslationAnswer.model_validate(
        {"translations": [{"n": 1, "text": "Một"}]}))
    view = partial.service.ensure(partial.user, partial.item)
    assert (view.status, view.translated, len(partial.store.rows)) == ("partial", 1, 1)


def test_someone_elses_library_item_is_not_translated():
    source = translation_service()
    with pytest.raises(LearnerLibraryError) as error:
        source.service.ensure(CurrentUser(id=uuid4()), source.item)
    assert error.value.status_code == 404
    source.provider.generate_structured.assert_not_called()


def test_the_translation_endpoint_answers_for_the_signed_in_learner():
    source = translation_service()
    sign_in(source.user)
    app.dependency_overrides[get_segment_translation_service] = lambda: source.service
    app.dependency_overrides[get_word_lookup_limiter] = lambda: SlidingWindowLimiter({"lookup": (10, 60.0)})
    try:
        client = TestClient(app)
        url = f"/api/v1/v3/learner/me/library/videos/{source.item}/translations"
        assert client.post(url).status_code == 401
        ok = client.post(url, headers=AUTH)
        assert ok.status_code == 200 and ok.json() == {"status": "ready", "language_code": "vi", "translated": 3}
    finally:
        app.dependency_overrides.clear()


# --- Practice rows carry the study region ---------------------------------------------------------------------

REGION = region_id(SENTENCE.id, SENTENCE.id)


def in_region_service():
    """The practice-log service whose sentence is both ends of REGION."""
    activity, log, _, _ = make_activity()
    service, foreign = log_service()
    service.learning_log = activity
    SENTENCE.sequence_number = 5
    foreign.sequence_number = 1
    return service, log, foreign


def test_a_dictation_attempt_logs_one_row_against_its_study_region_and_a_retry_adds_none():
    service, log, _ = in_region_service()
    request = DictationEventRequest(id=uuid4(), segment_id=SENTENCE.id, level="hard", answer="so I ended up",
                                    region_id=REGION)
    service.record_dictation(LEARNER, ITEM_ID, request)
    service.record_dictation(LEARNER, ITEM_ID, request)
    assert [(row.kind, row.source_type, row.source_id) for row in log.entries] == [("dictation", "video_region", REGION)]


def test_a_lookup_logs_against_its_region_and_a_region_that_does_not_hold_the_sentence_falls_back_to_the_video():
    service, log, foreign = in_region_service()
    span = dict(start_codepoint=5, end_codepoint=13)
    for region in (REGION, region_id(foreign.id, foreign.id), "junk"):
        service.record_lookup(LEARNER, ITEM_ID, LookupEventRequest(id=uuid4(), segment_id=SENTENCE.id,
                                                                   region_id=region, **span))
    assert [row.source_id for row in log.entries] == [REGION, str(ITEM_ID), str(ITEM_ID)]


def test_a_shadowing_attempt_logs_against_its_study_region(shadowing):  # noqa: F811
    activity, log, _, _ = make_activity()
    shadowing.service.learning_log = activity
    track = shadowing.transcripts.get_by_id.return_value
    segment = SimpleNamespace(id=shadowing.segment_id, transcript_id=track.id, sequence_number=2, start_ms=1000,
                              end_ms=4000, text="Before the leaves fall.")
    shadowing.service.segments.get_by_id.side_effect = lambda value: segment if value == shadowing.segment_id else None
    region = region_id(shadowing.segment_id, shadowing.segment_id)
    shadowing.service.assess(CurrentUser(id=SPEAKER), shadowing.item, shadowing.segment_id, speech(), region)
    assert [(row.kind, row.source_id) for row in log.entries] == [("shadowing", region)]


def test_a_region_question_answer_logs_against_the_learners_current_region():
    activity, log, _, _ = make_activity()
    region = region_id(SEGMENT, SEGMENT)
    service, _ = make_questions(CurrentRegionQuestionSet(status="ready", transcript_id=Q_TRACK, questions=(QUESTION,),
                                                         region_id=region))
    service.learning_log = activity
    service.transcripts = SimpleNamespace(get_by_id=lambda transcript_id: SimpleNamespace(language_code="en"))
    service.answer(SimpleNamespace(id=Q_OWNER), Q_ITEM, QUESTION.id,
                   RegionQuestionAnswerRequest(id=uuid4(), selected_option=0))
    assert [(row.kind, row.source_id) for row in log.entries] == [("region_question", region)]


def test_a_word_saved_from_a_lookup_in_a_region_counts_for_that_region():
    activity, log, _, _ = make_activity()
    words, _ = my_words_service()
    words.learning_log = activity
    region = region_id(uuid4(), uuid4())
    request = SaveFromOccurrence(source="occurrence", library_item_id=uuid4(), learning_object_id=uuid4(),
                                 region_id=region)
    words.save(me(), request)
    assert [(row.kind, row.source_type, row.source_id) for row in log.entries] == [("word_saved", "video_region", region)]


# --- The result card ------------------------------------------------------------------------------------------

def entry(kind, outcome, *, score=None, region=REGION, user=OWNER, item=None, **detail):
    return ActivityEntry(user_id=user, language_code="en", client_event_id=str(uuid4()), kind=kind, outcome=outcome,
                         score=score, item_type="segment", item_id=item or str(uuid4()), source_type="video_region",
                         source_id=region, detail=detail, occurred_at=datetime.now(UTC))


def result_service(entries):
    activity, log, _, _ = make_activity()
    for row in entries:
        activity.record(row)
    library = Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=uuid4()) if user_id == OWNER else None)
    return RegionResultService(library=library, activity=activity)


def test_the_result_sums_dictation_shadowing_questions_and_saved_words_of_one_region():
    question = str(uuid4())
    service = result_service([
        entry("dictation", "partial", score=60), entry("dictation", "correct", score=100),
        entry("shadowing", "correct", score=80), entry("shadowing", "partial", score=60),
        entry("region_question", "incorrect", question_id=question), entry("region_question", "correct", question_id=question),
        entry("region_question", "correct", question_id=str(uuid4())),
        entry("lookup", "done"), entry("word_saved", "done"),
        # everything below belongs elsewhere and must not count
        entry("dictation", "correct", score=100, region=region_id(uuid4(), uuid4())),
        entry("dictation", "correct", score=100, user=uuid4()), entry("word_saved", "done", user=uuid4()),
    ])
    result = service.result(LEARNER, ITEM_ID, REGION)
    assert (result.dictation_attempts, result.dictation_accuracy) == (2, 80.0)
    assert (result.shadowing_attempts, result.shadowing_average) == (2, 70.0)
    assert (result.questions_answered, result.questions_correct) == (2, 2)  # a question counts once, by its last answer
    assert (result.lookups, result.words_saved, result.practised) == (1, 1, True)


def test_the_result_of_an_untouched_region_is_empty_and_foreign_or_malformed_requests_are_refused():
    service = result_service([entry("dictation", "correct", score=100, user=uuid4())])
    empty = service.result(LEARNER, ITEM_ID, REGION)
    assert empty.practised is False and empty.dictation_accuracy is None and region_result(REGION, []) == empty
    with pytest.raises(PracticeLogError) as error:
        service.result(CurrentUser(id=uuid4()), ITEM_ID, REGION)
    assert error.value.status_code == 404
    with pytest.raises(PracticeLogError) as error:
        service.result(LEARNER, ITEM_ID, "not-a-region")
    assert error.value.code == "region_invalid"


def test_the_result_endpoint_returns_only_the_signed_in_learners_rows():
    service = result_service([entry("dictation", "correct", score=90),
                              entry("dictation", "correct", score=10, user=uuid4())])
    sign_in(LEARNER)
    app.dependency_overrides[get_region_result_service] = lambda: service
    try:
        client = TestClient(app)
        url = f"/api/v1/v3/learner/me/library/videos/{ITEM_ID}/regions/{REGION}/result"
        assert client.get(url).status_code == 401
        body = client.get(url, headers=AUTH).json()
        assert body["dictation_attempts"] == 1 and body["dictation_accuracy"] == 90.0
        bad = client.get(f"/api/v1/v3/learner/me/library/videos/{ITEM_ID}/regions/x/result", headers=AUTH)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "region_invalid"
    finally:
        app.dependency_overrides.clear()


# --- The older practice-events endpoints (Flutter) keep their shapes ------------------------------------------

def test_the_old_practice_event_endpoints_answer_in_their_old_shapes_without_a_region():
    activity, log, _, _ = make_activity()
    service, _ = log_service()
    service.learning_log = activity
    sign_in(LEARNER)
    app.dependency_overrides[get_practice_log_service] = lambda: service
    app.dependency_overrides[get_practice_log_limiter] = lambda: SlidingWindowLimiter({"practice_event": (100, 60.0)})
    base = f"/api/v1/v3/learner/me/library/videos/{ITEM_ID}/practice-events"
    try:
        client = TestClient(app)
        dictation = client.post(f"{base}/dictation", headers=AUTH, json={
            "id": str(uuid4()), "segment_id": str(SENTENCE.id), "level": "hard", "answer": "so I ended up taking a taxi"})
        assert dictation.status_code == 200
        assert set(dictation.json()) == {"id", "kind", "status", "total", "correct", "missed"}
        assert dictation.json()["kind"] == "dictation_checked" and dictation.json()["correct"] == 7
        lookup = client.post(f"{base}/lookup", headers=AUTH, json={
            "id": str(uuid4()), "segment_id": str(SENTENCE.id), "start_codepoint": 5, "end_codepoint": 13})
        assert lookup.status_code == 200 and lookup.json()["kind"] == "word_lookup"
    finally:
        app.dependency_overrides.clear()
    assert [row.source_id for row in log.entries] == [str(ITEM_ID), str(ITEM_ID)]
