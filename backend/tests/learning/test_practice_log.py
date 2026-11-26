"""M1 S4: the practice log (server-rechecked Dictation and lookups, written to the learning log only since
2026-11-18) and the companion's view of it."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.speaking import get_practice_log_limiter, get_practice_log_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.practice_log import (
    DictationEventRequest,
    LookupEventRequest,
    PracticeLogError,
    PracticeLogService,
)
from app.modules.learning.domain.companion import CompanionEntry
from app.modules.learning.domain.practice_log import (
    dictation_diff,
    dictation_summary,
    dictation_tokens,
    is_unspaced,
)
from app.platform.rate_limit import SlidingWindowLimiter
from tests.activity.fakes import BrokenLog, make_activity
from tests.learning.test_companion import ITEM_ID, OWNER, USER, make_service, speech, turn_output
from tests.learning.test_companion_region import REGION, SEG_B

OTHER = uuid4()
VIDEO_ID, TRACK_ID = uuid4(), uuid4()
SENTENCE = SimpleNamespace(id=uuid4(), transcript_id=TRACK_ID, text="So I ended up taking a taxi.",
                           start_ms=12_000, end_ms=15_500)


def log_service(*, language="en", log=None, video_status="learning_objects_ready"):
    library, videos, transcripts, segments = Mock(), Mock(), Mock(), Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=VIDEO_ID) if (library_item_id, user_id) == (ITEM_ID, OWNER) else None)
    videos.get_by_id.return_value = SimpleNamespace(id=VIDEO_ID, original_language_code=language,
                                                    processing_status=video_status)
    transcripts.get_by_id.side_effect = lambda transcript_id: SimpleNamespace(
        id=TRACK_ID, video_id=VIDEO_ID, is_original=True, language_code=language) if transcript_id == TRACK_ID else None
    foreign = SimpleNamespace(id=uuid4(), transcript_id=uuid4(), text="Elsewhere.")
    segments.get_by_id.side_effect = {SENTENCE.id: SENTENCE, foreign.id: foreign}.get
    activity, memory, _, _ = make_activity(log)
    service = PracticeLogService(library=library, videos=videos, transcripts=transcripts, segments=segments,
                                 learning_log=activity)
    service.log = memory
    return service, foreign


def dictation(**overrides):
    data = {"id": uuid4(), "segment_id": SENTENCE.id, "level": "hard", "answer": "so I end up taking taxi"}
    data.update(overrides)
    return DictationEventRequest(**data)


# --- Domain ---------------------------------------------------------------------------

def test_tokens_and_diff_match_the_web_panel_rules():
    assert dictation_tokens("So, I ended-up taking a TAXI!", False) == ["So", "I", "ended-up", "taking", "a", "TAXI"]
    assert dictation_tokens("我坐了出租车。", True) == ["我", "坐", "了", "出", "租", "车"]
    kinds = [kind for kind, _, _ in dictation_diff(["So", "I", "ended", "up"], ["so", "i", "end", "up", "now"])]
    assert kinds == ["correct", "correct", "wrong", "correct", "extra"]
    assert is_unspaced("zh-CN") and is_unspaced("ja") and not is_unspaced("en")


def test_the_summary_keeps_counts_and_a_few_missed_words_never_the_answer():
    summary = dictation_summary(SENTENCE.text, "so I end up taking taxi", unspaced=False, level="hard", hint_shown=True)
    assert summary["total"] == 7 and summary["correct"] == 5 and summary["missed"] == ["ended", "a"]
    assert summary["client_reported"] == {"hint_shown": True}
    assert "end up taking" not in str(summary)


# --- Service ---------------------------------------------------------------------------

def test_dictation_is_rechecked_by_the_server_and_stored_once_per_id():
    service, _ = log_service()
    request = dictation()
    first = service.record_dictation(USER, ITEM_ID, request)
    again = service.record_dictation(USER, ITEM_ID, request)
    assert (first.status, again.status) == ("created", "reused")
    assert (first.total, first.correct, first.missed) == (7, 5, ["ended", "a"])
    [row] = service.log.of("dictation")  # one learning-log row per id
    assert (row.outcome, row.item_type, row.item_id) == ("partial", "segment", str(SENTENCE.id))
    assert row.detail == {"total": 7, "correct": 5, "missed": ["ended", "a"], "level": "hard"}
    assert "end up taking" not in str(row.detail)  # never the learner's answer


def test_chinese_dictation_counts_characters():
    service, _ = log_service(language="zh")
    service.segments.get_by_id.side_effect = lambda _id: SimpleNamespace(id=SENTENCE.id, transcript_id=TRACK_ID,
                                                                         text="我坐了出租车。")
    view = service.record_dictation(USER, ITEM_ID, dictation(answer="我坐出租车"))
    assert (view.total, view.correct, view.missed) == (6, 5, ["了"])


def test_wrong_owner_foreign_sentence_and_unready_video_are_refused():
    service, foreign = log_service()
    with pytest.raises(PracticeLogError) as other:
        service.record_dictation(CurrentUser(id=OTHER), ITEM_ID, dictation())
    with pytest.raises(PracticeLogError) as elsewhere:
        service.record_dictation(USER, ITEM_ID, dictation(segment_id=foreign.id))
    assert (other.value.status_code, elsewhere.value.status_code) == (404, 404)
    unready, _ = log_service(video_status="pending")
    with pytest.raises(PracticeLogError) as waiting:
        unready.record_dictation(USER, ITEM_ID, dictation())
    assert waiting.value.code == "video_not_ready"
    assert service.log.entries == []


def test_lookups_store_the_server_text_of_a_valid_span_only():
    service, _ = log_service()
    view = service.record_lookup(USER, ITEM_ID, LookupEventRequest(id=uuid4(), segment_id=SENTENCE.id,
                                                                   start_codepoint=5, end_codepoint=13))
    assert view.kind == "word_lookup"
    assert service.log.of("lookup")[0].detail == {"text": "ended up"}
    for start, end in [(5, 99), (13, 5), (0, 28 + 50)]:
        with pytest.raises((PracticeLogError, ValidationError)):
            service.record_lookup(USER, ITEM_ID, LookupEventRequest(id=uuid4(), segment_id=SENTENCE.id,
                                                                    start_codepoint=start, end_codepoint=end))


def test_requests_carry_selectors_and_raw_input_only():
    with pytest.raises(ValidationError):
        DictationEventRequest(id=uuid4(), segment_id=SENTENCE.id, level="hard", answer="x", correct=7)
    with pytest.raises(ValidationError):
        DictationEventRequest(id=uuid4(), segment_id=SENTENCE.id, level="perfect", answer="x")
    with pytest.raises(ValidationError):
        DictationEventRequest(id=uuid4(), segment_id=SENTENCE.id, level="hard", answer="x" * 601)


def test_a_learning_log_failure_never_fails_the_dictation_check():
    service, _ = log_service(log=BrokenLog())
    view = service.record_dictation(USER, ITEM_ID, dictation())
    assert (view.total, view.correct) == (7, 5)  # the learner still gets the server's check


# --- Companion ------------------------------------------------------------------------

def test_the_companion_sees_recent_practice_in_the_region_from_the_learning_log_by_region_line():
    from tests.learning.test_companion import FakeFacts
    service = make_service(outputs=(turn_output(), turn_output()), texts=["I could not hear it"])
    reader = Mock()
    reader.for_learner.return_value = REGION
    service.regions = reader
    service.facts = FakeFacts()
    first = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert "<practice>\n" not in service.model.prompts[0]
    region_id = service.load(USER, first.session_ticket).ticket.region_id
    assert region_id == f"{REGION.lines[0].segment_id}_{REGION.lines[-1].segment_id}"
    # The learner opens the suggested Dictation during the conversation; the flow writes one log row.
    service.facts.region = [{"kind": "dictation", "outcome": "partial", "segment_id": SEG_B,
                             "detail": {"total": 6, "correct": 4, "missed": ["ended", "up"]}}]
    service.turn(USER, first.session_ticket, speech())
    assert "<practice>\n- dictation of s2: 4 of 6 right; missed: ended, up\n</practice>" in service.model.prompts[1]
    assert "never score it" in service.model.prompts[1]
    assert ("region_activity", OWNER, region_id) in service.facts.calls


def test_a_learning_log_failure_never_fails_a_companion_turn():
    from tests.learning.test_companion import FakeFacts

    class Broken(FakeFacts):
        def region_activity(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    service = make_service()
    reader = Mock()
    reader.for_learner.return_value = REGION
    service.regions = reader
    service.facts = Broken()
    assert service.start(USER, CompanionEntry.VIDEO, ITEM_ID).reply
    assert "<practice>\n" not in service.model.prompts[0]


# --- Repository and API -----------------------------------------------------------------

@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=OWNER)
    service, _ = log_service()
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_practice_log_service] = lambda: service
    limiter = SlidingWindowLimiter({"practice_event": (1, 60)})
    app.dependency_overrides[get_practice_log_limiter] = lambda: limiter
    try:
        yield SimpleNamespace(client=TestClient(app), headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_the_api_rejects_client_authority_and_is_rate_limited(api):
    url = f"/api/v1/v3/learner/me/library/videos/{ITEM_ID}/practice-events/dictation"
    body = {"id": str(uuid4()), "segment_id": str(SENTENCE.id), "level": "hard", "answer": "so I ended up"}
    assert api.client.post(url, json=body).status_code == 401
    assert api.client.post(url, headers=api.headers, json={**body, "correct": 99}).status_code == 422
    created = api.client.post(url, headers=api.headers, json=body)
    assert created.status_code == 200 and created.json()["status"] == "created"
    assert "answer" not in created.json()
    assert api.client.post(url, headers=api.headers, json=body).status_code == 429
