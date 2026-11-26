from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.speaking import (
    get_shadowing_practice_service,
    get_speaking_rate_limiter,
)
from app.platform.rate_limit import SlidingWindowLimiter
from app.modules.identity.contracts import CurrentUser
from app.main import app
from app.modules.learning.application.learned_items import LearnedItemCatalog
from app.modules.learning.application.shadowing import ShadowingPracticeService
from app.modules.learning.application.speaking_ports import (
    NoSpeechDetected,
    SpeakingPracticeError,
    SpeechProviderFailure,
)
from app.modules.learning.domain.speaking import (
    PronunciationErrorType,
    PronunciationResult,
    PronunciationScores,
    PronunciationWord,
)
from app.modules.learning.domain.speech_audio import SpeechAudio
from tests.learning.speaking_fixtures import pcm_silence, pcm_tone, speech_like_wav, wav_bytes

OWNER, OTHER = uuid4(), uuid4()


def result(score=82.0, text="Before the leaves fall."):
    return PronunciationResult(
        recognized_text=text,
        scores=PronunciationScores(pronunciation=score, accuracy=75, fluency=95, completeness=79, prosody=None),
        words=(PronunciationWord("before", 97, PronunciationErrorType.NONE, 80, 510),
               PronunciationWord("leaves", 40, PronunciationErrorType.MISPRONUNCIATION, 520, 820)),
    )


class FakeAssessor:
    provider_name = "fake"

    def __init__(self, outcome=None, languages=("en",)):
        self.outcome = outcome if outcome is not None else result()
        self.languages = languages
        self.calls = []

    def supports(self, language_code):
        return language_code in self.languages

    def assess(self, audio, *, reference_text, language_code):
        self.calls.append((reference_text, language_code))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


# --- Shadowing service -------------------------------------------------------------

@pytest.fixture
def shadowing():
    item, video_id, track_id, segment_id = uuid4(), uuid4(), uuid4(), uuid4()
    library, videos, transcripts, segments = Mock(), Mock(), Mock(), Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=video_id) if (library_item_id, user_id) == (item, OWNER) else None)
    videos.get_by_id.return_value = SimpleNamespace(id=video_id, processing_status="transcript_ready",
                                                    original_language_code="en")
    transcripts.get_by_id.return_value = SimpleNamespace(id=track_id, video_id=video_id, is_original=True,
                                                         language_code="en")
    segments.get_by_id.side_effect = lambda value: (
        SimpleNamespace(id=segment_id, transcript_id=track_id, start_ms=1000, end_ms=4000,
                        text="  Before the leaves   fall. ") if value == segment_id else None)
    assessor = FakeAssessor()
    service = ShadowingPracticeService(library=library, videos=videos, transcripts=transcripts,
                                       segments=segments, assessor=assessor)
    return SimpleNamespace(service=service, item=item, segment_id=segment_id, assessor=assessor,
                           videos=videos, transcripts=transcripts, video_id=video_id)


def speech(ms=2000):
    return SpeechAudio(pcm_tone(ms))


def kind_of(callable_):
    with pytest.raises(SpeakingPracticeError) as raised:
        callable_()
    return raised.value.kind, raised.value.code


def test_shadowing_uses_server_reference_and_returns_safe_projection(shadowing):
    view = shadowing.service.assess(CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id, speech())
    assert shadowing.assessor.calls == [("Before the leaves fall.", "en")]
    assert view.band.value == "good" and view.reference_duration_ms == 3000
    assert view.spoken_duration_ms == 740
    assert set(view.model_dump()) == {
        "library_item_id", "segment_id", "language_code", "reference_text", "recognized_text", "band",
        "scores", "words", "attempt_duration_ms", "reference_duration_ms", "spoken_duration_ms"}


def test_shadowing_rejects_wrong_owner_and_foreign_segments(shadowing):
    other = CurrentUser(id=OTHER)
    assert kind_of(lambda: shadowing.service.assess(other, shadowing.item, shadowing.segment_id, speech())) == (
        "not_found", "library_item_not_found")
    assert kind_of(lambda: shadowing.service.assess(CurrentUser(id=OWNER), shadowing.item, uuid4(), speech())) == (
        "not_found", "segment_not_found")
    shadowing.transcripts.get_by_id.return_value = SimpleNamespace(
        video_id=uuid4(), is_original=True, language_code="en")
    assert kind_of(lambda: shadowing.service.assess(
        CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id, speech()))[1] == "segment_not_found"
    shadowing.transcripts.get_by_id.return_value = SimpleNamespace(
        video_id=shadowing.video_id, is_original=False, language_code="en")
    assert kind_of(lambda: shadowing.service.assess(
        CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id, speech()))[1] == "segment_not_found"
    assert shadowing.assessor.calls == []


def test_shadowing_checks_readiness_language_and_audio_before_provider(shadowing):
    user = CurrentUser(id=OWNER)
    shadowing.videos.get_by_id.return_value = SimpleNamespace(
        id=shadowing.video_id, processing_status="pending", original_language_code="en")
    assert kind_of(lambda: shadowing.service.assess(user, shadowing.item, shadowing.segment_id, speech()))[1] == \
        "video_not_ready"
    shadowing.videos.get_by_id.return_value = SimpleNamespace(
        id=shadowing.video_id, processing_status="transcript_ready", original_language_code="en")
    assert kind_of(lambda: shadowing.service.assess(
        user, shadowing.item, shadowing.segment_id, SpeechAudio(pcm_silence(2000))))[1] == "no_speech_detected"
    assert kind_of(lambda: shadowing.service.assess(user, shadowing.item, shadowing.segment_id, speech(16_000)))[1] \
        == "audio_too_long"
    shadowing.assessor.languages = ()
    assert kind_of(lambda: shadowing.service.assess(user, shadowing.item, shadowing.segment_id, speech())) == (
        "unsupported", "speaking_language_unsupported")
    assert shadowing.assessor.calls == []


@pytest.mark.parametrize("outcome,expected", [
    (NoSpeechDetected(), ("invalid_input", "no_speech_detected")),
    (SpeechProviderFailure("busy"), ("unavailable", "speech_service_busy")),
    (SpeechProviderFailure("configuration"), ("unavailable", "speech_service_unavailable")),
])
def test_shadowing_provider_outcomes_are_never_learner_failure(shadowing, outcome, expected):
    shadowing.assessor.outcome = outcome
    assert kind_of(lambda: shadowing.service.assess(
        CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id, speech())) == expected


def test_shadowing_without_configured_provider_is_unavailable(shadowing):
    shadowing.service.assessor = None
    assert kind_of(lambda: shadowing.service.assess(
        CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id, speech()))[1] == "speech_service_unavailable"


# --- Learned items projection --------------------------------------------------------

def test_learned_items_use_only_ready_same_language_library_videos():
    from app.modules.content.domain.knowledge import Concept, ConceptType
    ready, other_language, not_ready = uuid4(), uuid4(), uuid4()
    first_concept, second_concept = uuid4(), uuid4()
    library = Mock()
    library.list_for_user.return_value = [SimpleNamespace(video_id=value) for value in (ready, other_language, not_ready)]
    videos = Mock()
    videos.get_many_by_ids.side_effect = lambda ids: {value: SimpleNamespace(
        id=value, original_language_code="ja" if value == other_language else "en",
        learning_status="processing" if value == not_ready else "ready") for value in ids}
    meaning = {"concept_id": str(second_concept), "concept_sense_key": "sense", "source_language_code": "en",
               "target_language_code": "vi", "contextual_meaning": "thường xuyên"}
    learning_objects = Mock()
    learning_objects.list_for_videos.side_effect = lambda values: [
        SimpleNamespace(video_id=ready, concept_id=first_concept, evidence_text="prefers", raw_ai_diagnostics=None),
        SimpleNamespace(video_id=ready, concept_id=second_concept, evidence_text="usually",
                        raw_ai_diagnostics={"enrichments": {"vi": meaning}}),
    ] if values == [ready] else pytest.fail("only ready same-language videos are read")
    concepts = Mock()
    concepts.list_by_ids.return_value = [
        Concept(id=first_concept, language_code="en", type=ConceptType.VOCABULARY, canonical_text="prefer",
                normalized_text="prefer", sense_key="sense"),
        Concept(id=second_concept, language_code="en", type=ConceptType.VOCABULARY, canonical_text="usually",
                normalized_text="usually", sense_key="sense"),
    ]
    items = LearnedItemCatalog(library=library, videos=videos, learning_objects=learning_objects,
                               concepts=concepts).for_learner(
        OWNER, language_code="en", support_language_code="vi")

    assert [(item.text, item.source, item.meaning) for item in items] == [
        ("prefer", "from_video", None), ("usually", "from_video", "thường xuyên")]
    assert items[0].forms == ("prefer", "prefers")


# --- HTTP surface ----------------------------------------------------------------------

class FakeShadowing:
    def __init__(self):
        self.calls = []

    def assess(self, user, library_item_id, segment_id, audio, region_id=None):
        self.calls.append((user.id, library_item_id, segment_id, audio.duration_ms))
        if segment_id.int == 0:
            raise SpeakingPracticeError("not_found", "segment_not_found", "Sentence not found.")
        from app.modules.learning.application.speaking_views import ShadowingAssessmentView, SpeakingScoresView
        return ShadowingAssessmentView(
            library_item_id=library_item_id, segment_id=segment_id, language_code="en", reference_text="Hi",
            recognized_text="Hi", band="good", words=[], attempt_duration_ms=audio.duration_ms,
            reference_duration_ms=1000, scores=SpeakingScoresView(pronunciation=80, accuracy=80, fluency=80,
                                                                  completeness=80))


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=OWNER)
    shadowing_service = FakeShadowing()
    limiter = SlidingWindowLimiter({"shadowing": (2, 60)})
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_shadowing_practice_service] = lambda: shadowing_service
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: limiter
    try:
        yield SimpleNamespace(client=TestClient(app), shadowing=shadowing_service,
                              headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def shadowing_url(item):
    return f"/api/v1/v3/learner/me/library/videos/{item}/shadowing/assessments"


def test_shadowing_endpoint_requires_auth_and_valid_wav(api):
    item = uuid4()
    files = {"audio": ("a.wav", speech_like_wav(1500), "audio/wav")}
    assert api.client.post(shadowing_url(item), data={"segment_id": str(uuid4())}, files=files).status_code == 401
    bad = api.client.post(shadowing_url(item), headers=api.headers, data={"segment_id": str(uuid4())},
                          files={"audio": ("a.wav", wav_bytes(pcm_tone(1000), rate=44_100), "audio/wav")})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "audio_format_unsupported"
    too_large = api.client.post(shadowing_url(item), headers=api.headers, data={"segment_id": str(uuid4())},
                                files={"audio": ("a.wav", b"0" * 2_600_001, "audio/wav")})
    assert too_large.status_code == 413
    assert api.shadowing.calls == []


def test_shadowing_endpoint_maps_results_errors_and_rate_limits(api):
    item, segment = uuid4(), uuid4()
    files = {"audio": ("a.wav", speech_like_wav(1500), "audio/wav")}
    ok = api.client.post(shadowing_url(item), headers=api.headers, data={"segment_id": str(segment)}, files=files)
    assert ok.status_code == 200 and ok.json()["scores"]["pronunciation"] == 80
    assert api.shadowing.calls == [(OWNER, item, segment, 1500)]
    missing = api.client.post(shadowing_url(item), headers=api.headers,
                              data={"segment_id": "00000000-0000-0000-0000-000000000000"},
                              files={"audio": ("a.wav", speech_like_wav(1500), "audio/wav")})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "segment_not_found"
    limited = api.client.post(shadowing_url(item), headers=api.headers, data={"segment_id": str(segment)},
                              files={"audio": ("a.wav", speech_like_wav(1500), "audio/wav")})
    assert limited.status_code == 429 and limited.json()["detail"]["code"] == "speaking_rate_limited"


def test_rate_limiter_window_expires():
    now = [0.0]
    limiter = SlidingWindowLimiter({"a": (1, 10)}, clock=lambda: now[0])
    assert limiter.allow("u", "a") and not limiter.allow("u", "a") and limiter.allow("v", "a")
    now[0] = 10.5
    assert limiter.allow("u", "a")
