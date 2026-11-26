from types import SimpleNamespace
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid4


from app.modules.content.domain.knowledge import LearningObject
from app.modules.content.domain.extraction import (
    Candidate,
    CandidateExtractionResult,
    CandidateType,
)
from app.modules.content.domain.catalog import TranscriptSegment, Video, VideoTranscript
from app.modules.content.application.knowledge_resolution import V3CandidateResolutionService
from app.modules.content.application.preparation import LearningContentPreparationService
from app.modules.content.application.enrichment import LearningObjectEnrichmentError
from app.modules.content.worker import tasks as worker


VIDEO_ID = UUID("a0000000-0000-0000-0000-000000000001")
TRANSCRIPT_ID = UUID("a0000000-0000-0000-0000-000000000002")
CONCEPT_ID = UUID("a0000000-0000-0000-0000-000000000003")
SEGMENT_1 = TranscriptSegment(
    id=uuid4(), transcript_id=TRANSCRIPT_ID, sequence_number=1,
    start_ms=0, end_ms=2000, text="bank by the river bank",
)
SEGMENT_2 = TranscriptSegment(
    id=uuid4(), transcript_id=TRANSCRIPT_ID, sequence_number=2,
    start_ms=2000, end_ms=4000, text="put it off, then put it off",
)


def object_for(segment, start, end, *, concept_id=CONCEPT_ID):
    return LearningObject(
        id=uuid4(), concept_id=concept_id, video_id=VIDEO_ID,
        transcript_segment_id=segment.id, occurrence_index=1,
        evidence_text=segment.text[start:end], start_codepoint=start,
        end_codepoint=end, start_ms=segment.start_ms, end_ms=segment.end_ms,
    )


class Videos:
    def __init__(self):
        self.video = Video(
            id=VIDEO_ID, source="youtube", external_video_id="sample",
            original_language_code="en", title="sample",
            processing_status="transcript_ready", learning_status="not_started",
        )
        self.claims = 0

    def get_by_id(self, video_id):
        return self.video if video_id == VIDEO_ID else None

    def claim_learning_preparation(self, video_id, *, version):
        if video_id != VIDEO_ID or self.video.learning_status != "not_started":
            return None
        self.claims += 1
        self.video = self.video.model_copy(update={
            "learning_status": "processing", "learning_preparation_version": version,
        })
        return self.video

    def finish_learning_preparation(self, video_id, *, status, usable_count,
                                    support_language_code, failure_code=None, retryable=False):
        if video_id != VIDEO_ID or self.video.learning_status != "processing":
            return None
        self.video = self.video.model_copy(update={
            "learning_status": status, "learning_object_count": usable_count,
            "learning_prepared_language_code": support_language_code,
            "learning_failure_code": failure_code, "learning_retryable": retryable,
        })
        return self.video


class Transcripts:
    def list_for_video(self, video_id):
        return [VideoTranscript(
            id=TRANSCRIPT_ID, video_id=video_id, language_code="en", is_original=True,
        )]


class Segments:
    def __init__(self):
        self.rows = [SEGMENT_1, SEGMENT_2]

    def list_for_transcript(self, transcript_id):
        return self.rows if transcript_id == TRANSCRIPT_ID else []

    def get_by_id(self, segment_id):
        return next((row for row in self.rows if row.id == segment_id), None)


class Objects:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def list_for_video(self, video_id):
        return [row for row in self.rows if row.video_id == video_id]


class Resolution:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def extract_and_resolve_by_segment_id(self, segment_id, **context):
        self.calls.append((segment_id, context))
        objects, errors = self.results.get(segment_id, ([], []))
        return SimpleNamespace(
            resolved=[SimpleNamespace(learning_object=row) for row in objects],
            errors=errors,
        )


class Enrichment:
    def __init__(self, failed=()):
        self.failed = set(failed)
        self.calls = []

    def enrich(self, object_id, *, target_language_code):
        self.calls.append((object_id, target_language_code))
        if object_id in self.failed:
            raise LearningObjectEnrichmentError("provider unavailable")
        return SimpleNamespace(contextual_meaning="nghĩa trong ngữ cảnh")


def make_service(*, results=None, existing=(), failed=()):
    videos = Videos()
    videos.claim_learning_preparation(VIDEO_ID, version="v6a6-1")
    resolution = Resolution(results)
    enrichment = Enrichment(failed)
    service = LearningContentPreparationService(
        videos=videos, transcripts=Transcripts(), segments=Segments(),
        learning_objects=Objects(existing), resolution=resolution,
        enrichment=enrichment, support_language_code="vi", max_segments=20,
    )
    return service, videos, resolution, enrichment


def test_ready_uses_persisted_spans_and_enriches_exact_objects():
    river = object_for(SEGMENT_1, 18, 22, concept_id=uuid4())
    finance = object_for(SEGMENT_1, 0, 4, concept_id=uuid4())
    service, videos, _, enrichment = make_service(results={SEGMENT_1.id: ([finance, river], [])})
    outcome = service.prepare_claimed(VIDEO_ID)
    assert outcome.status == "ready" and outcome.usable_count == 2
    assert videos.video.learning_prepared_language_code == "vi"
    assert {item[0] for item in enrichment.calls} == {finance.id, river.id}


def test_repeated_same_concept_occurrences_remain_distinct():
    first = object_for(SEGMENT_2, 0, 10)
    second = object_for(SEGMENT_2, 17, 27)
    service, _, _, enrichment = make_service(results={SEGMENT_2.id: ([first, second], [])})
    assert service.prepare_claimed(VIDEO_ID).usable_count == 2
    assert {item[0] for item in enrichment.calls} == {first.id, second.id}


def test_a_concept_is_prepared_at_most_twice_per_video_earliest_first():
    # "put it off" appears twice in segment 2 and once more (as existing data) in segment 1.
    later = object_for(SEGMENT_2, 17, 27)
    earliest = object_for(SEGMENT_1, 0, 4)
    middle = object_for(SEGMENT_2, 0, 10)
    other = object_for(SEGMENT_2, 4, 6, concept_id=uuid4())
    service, _, _, enrichment = make_service(existing=[later], results={
        SEGMENT_1.id: ([earliest], []), SEGMENT_2.id: ([middle, later, other], [])})

    outcome = service.prepare_claimed(VIDEO_ID)

    assert [item[0] for item in enrichment.calls] == [earliest.id, middle.id, other.id]
    assert outcome.usable_count == 3 and outcome.partial_failures == 0


def test_partial_enrichment_failure_retains_usable_content():
    good = object_for(SEGMENT_1, 0, 4)
    bad = object_for(SEGMENT_1, 18, 22)
    service, videos, _, _ = make_service(
        results={SEGMENT_1.id: ([good, bad], ["one candidate failed"])}, failed=[bad.id],
    )
    outcome = service.prepare_claimed(VIDEO_ID)
    assert outcome.status == "ready" and outcome.usable_count == 1
    assert outcome.partial_failures == 2
    assert videos.video.processing_status == "transcript_ready"


def test_zero_valid_candidates_is_no_content_not_failure():
    service, videos, _, _ = make_service()
    assert service.prepare_claimed(VIDEO_ID).status == "no_content"
    assert videos.video.processing_status == "transcript_ready"


def test_provider_or_enrichment_failure_is_retryable_learning_failure():
    item = object_for(SEGMENT_1, 0, 4)
    service, videos, _, _ = make_service(
        results={SEGMENT_1.id: ([item], ["provider failed"])}, failed=[item.id],
    )
    outcome = service.prepare_claimed(VIDEO_ID)
    assert outcome.status == "failed"
    assert videos.video.learning_retryable is True
    assert videos.video.processing_status == "transcript_ready"


def test_retry_reuses_existing_trusted_object_even_if_extraction_fails():
    item = object_for(SEGMENT_1, 0, 4)
    service, videos, _, enrichment = make_service(
        existing=[item], results={SEGMENT_1.id: ([], ["provider failed"])},
    )
    outcome = service.prepare_claimed(VIDEO_ID)
    assert outcome.status == "ready" and outcome.usable_count == 1
    assert enrichment.calls == [(item.id, "vi")]
    assert videos.video.learning_object_count == 1


def test_stale_or_ungrounded_existing_object_is_not_counted():
    stale = object_for(SEGMENT_1, 0, 4).model_copy(update={"evidence_text": "invented"})
    service, videos, _, enrichment = make_service(existing=[stale])
    assert service.prepare_claimed(VIDEO_ID).status == "no_content"
    assert enrichment.calls == []
    assert videos.video.learning_object_count == 0


def test_duplicate_worker_delivery_claims_only_once(monkeypatch):
    videos = Videos()
    outcome = SimpleNamespace(status="ready", usable_count=1, failure_code=None)

    class Intents:
        state = "pending"

        def get(self, intent_id):
            return SimpleNamespace(id=intent_id, video_id=VIDEO_ID, stage="learning_preparation")

        def claim(self, intent_id, *, preparation_version=None, lease_seconds):
            if self.state != "pending":
                return None
            assert preparation_version
            self.state = "running"
            videos.claim_learning_preparation(VIDEO_ID, version=preparation_version)
            return SimpleNamespace(intent_id=intent_id, video_id=VIDEO_ID, stage="learning_preparation",
                                   generation=1, epoch=1, lease_expires_at=datetime.now(UTC))

        def finish_preparation(self, claim, *, status, usable_count, support_language_code, failure_code):
            assert status == "ready" and usable_count == 1
            videos.finish_learning_preparation(claim.video_id, status=status, usable_count=usable_count,
                                               support_language_code=support_language_code)
            self.state = "completed"

    intents = Intents()

    class ClaimedService:
        support_language_code = "vi"

        def prepare_claimed(self, video_id, *, persist_terminal):
            assert video_id == VIDEO_ID
            assert persist_terminal is False
            return outcome

    monkeypatch.setattr(worker, "supabase_service", object())
    monkeypatch.setattr(worker, "build_work_intents", lambda _: intents)
    monkeypatch.setattr(worker, "build_content_ingestion_service", lambda _: SimpleNamespace(videos=videos))
    monkeypatch.setattr(worker, "build_learning_content_preparation_service", lambda _, **kwargs: ClaimedService())
    first = worker.prepare_video_learning_content.run(str(VIDEO_ID))
    second = worker.prepare_video_learning_content.run(str(VIDEO_ID))
    assert first["status"] == "ready"
    assert second["status"] == "not_claimed"
    assert videos.claims == 1


def test_transcript_success_dispatches_background_learning(monkeypatch):
    delivered = []
    preparation_id = uuid4()

    class Intents:
        def get(self, intent_id):
            return SimpleNamespace(id=intent_id, video_id=VIDEO_ID, stage="transcript")

        def claim(self, intent_id, *, lease_seconds):
            return SimpleNamespace(intent_id=intent_id, video_id=VIDEO_ID, stage="transcript",
                                   generation=1, epoch=1, lease_expires_at=datetime.now(UTC))

        def active_for_video(self, *, video_id, stage):
            assert video_id == VIDEO_ID and stage == "learning_preparation"
            return SimpleNamespace(id=preparation_id)

    class ContentVideos:
        def claim_pending_processing(self, video_id):
            return SimpleNamespace(id=video_id)

    class Content:
        videos = ContentVideos()

        def process_video(self, video_id, *, processing_already_claimed, work_intent_id, execution_claim):
            assert processing_already_claimed is True
            assert work_intent_id == VIDEO_ID
            return SimpleNamespace(segments=[SEGMENT_1])

    monkeypatch.setattr(worker, "supabase_service", object())
    monkeypatch.setattr(worker, "build_work_intents", lambda _: Intents())
    monkeypatch.setattr(worker, "build_content_ingestion_service", lambda _, **kwargs: Content())
    monkeypatch.setattr(
        worker.ContentWorkDispatcher, "dispatch",
        lambda self, intent_id: delivered.append(intent_id),
    )
    result = worker.process_prepared_video_v3.run(str(VIDEO_ID))
    assert result["status"] == "ready"
    assert delivered == [preparation_id]


def test_committed_transcript_handoff_survives_fast_path_lookup_failure(monkeypatch):
    class Intents:
        def get(self, intent_id):
            return SimpleNamespace(id=intent_id, video_id=VIDEO_ID, stage="transcript")

        def claim(self, intent_id, *, lease_seconds):
            return SimpleNamespace(intent_id=intent_id, video_id=VIDEO_ID, stage="transcript",
                                   generation=1, epoch=1, lease_expires_at=datetime.now(UTC))

        def active_for_video(self, *, video_id, stage):
            raise ConnectionError("receipt lost after committed handoff")

    class Content:
        videos = object()

        def process_video(self, video_id, *, processing_already_claimed, work_intent_id, execution_claim):
            return SimpleNamespace(segments=[SEGMENT_1])

    monkeypatch.setattr(worker, "supabase_service", object())
    monkeypatch.setattr(worker, "build_work_intents", lambda _: Intents())
    monkeypatch.setattr(worker, "build_content_ingestion_service", lambda _, **kwargs: Content())

    assert worker.process_prepared_video_v3.run(str(VIDEO_ID))["status"] == "ready"


def test_retry_warning_does_not_discard_eventually_grounded_candidates():
    candidate = Candidate(
        surface_form="bank", normalized_form="bank", sense_gloss="financial institution",
        sense_evidence="bank by the river bank", candidate_type=CandidateType.WORD,
        evidence_start=0, evidence_end=4, source_segment_id=SEGMENT_1.id,
        confidence=0.9,
    )
    extraction = CandidateExtractionResult(
        source_segment_id=SEGMENT_1.id, candidates=[candidate],
        extraction_metadata={"attempts": 2}, errors=["LLMProviderError"],
    )
    resolution = Mock()
    resolution.resolve_candidates.return_value = SimpleNamespace(errors=[], resolved=[])
    service = V3CandidateResolutionService(
        segments=Mock(), transcripts=Mock(), extraction=Mock(), resolution=resolution,
    )
    transcript = VideoTranscript(id=TRANSCRIPT_ID, video_id=VIDEO_ID, language_code="en", is_original=True)
    service.resolve_extraction_result(
        extraction_result=extraction, segment=SEGMENT_1, transcript=transcript,
    )
    resolution.resolve_candidates.assert_called_once()
    terminal = extraction.model_copy(update={"extraction_metadata": {"failed_closed": True}})
    service.resolve_extraction_result(
        extraction_result=terminal, segment=SEGMENT_1, transcript=transcript,
    )
    resolution.resolve_candidates.assert_called_once()
