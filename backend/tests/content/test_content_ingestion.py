from uuid import UUID, uuid4


from app.modules.content.application.ports import SourceProviderError
from app.modules.content.domain.ingestion import (
    SourceTranscriptSegment,
    SourceTranscriptTrack,
    SourceVideoMetadata,
)
from app.modules.content.domain.library import ContentProcessingFailureCode
from app.modules.content.domain.catalog import (
    Channel,
    Language,
    RomanizationSystem,
    TranscriptSegment,
    Video,
    VideoTranscript,
)
from app.modules.content.application.ingestion import ContentIngestionError, ContentIngestionService
from app.modules.content.domain.normalizer import TranscriptNormalizer


USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")


class FakeProvider:
    def extract_external_video_id(self, url: str) -> str:
        if "yt-123" not in url:
            raise ValueError("Invalid YouTube URL")
        return "yt-123"

    def get_video_metadata(self, url: str) -> SourceVideoMetadata:
        return SourceVideoMetadata(
            external_video_id="yt-123",
            watch_url=url,
            title="A Useful Video",
            thumbnail_url="https://example.test/thumb.jpg",
            original_language_code="zh",
            external_channel_id="channel-123",
            channel_name="Language Channel",
            channel_url="https://youtube.com/@language",
        )

    def get_original_transcript(self, external_video_id: str, language_code: str):
        return SourceTranscriptTrack(
            language_code=language_code,
            is_original=True,
            segments=[
                SourceTranscriptSegment(sequence_number=2, start_seconds=1.5, duration_seconds=0.5, text="  第二句\n"),
                SourceTranscriptSegment(sequence_number=1, start_seconds=0, duration_seconds=1.0, text="第一句"),
                SourceTranscriptSegment(sequence_number=3, start_seconds=2, duration_seconds=0.5, text=" "),
            ],
        )

    def get_translated_transcript(self, external_video_id: str, target_language_code: str):
        return SourceTranscriptTrack(
            language_code=target_language_code,
            is_original=False,
            segments=[
                SourceTranscriptSegment(sequence_number=1, start_seconds=0, duration_seconds=1.0, text="Sentence one"),
                SourceTranscriptSegment(sequence_number=2, start_seconds=1.5, duration_seconds=0.5, text="Sentence two"),
            ],
        )


class FakeRomanizationProvider:
    def romanize(self, text: str, language_code: str) -> dict[str, str]:
        return {"pinyin": f"pin-{text}"} if language_code == "zh" else {}


class FakeLanguages:
    def get_active(self, code: str):
        if code in {"zh", "en"}:
            return Language(
                code=code,
                name_en=code,
                name_native=code,
                script="Latin",
                is_active=True,
                display_order=1,
            )
        return None


class FakeChannels:
    def __init__(self):
        self.rows = {}

    def upsert_by_source_external(self, data: dict):
        key = (data["source"], data["external_channel_id"])
        row = self.rows.get(key) or {"id": uuid4(), **data}
        row.update(data)
        self.rows[key] = row
        return Channel(**row)


class FakeVideos:
    def __init__(self):
        self.rows = {}
        self.status_history = []

    def upsert_by_source_external(self, data: dict):
        key = (data["source"], data["external_video_id"])
        row = self.rows.get(key) or {"id": uuid4(), **data}
        row.update(data)
        self.rows[key] = row
        return Video(**row)

    def create_pending_by_source_external(self, data: dict):
        key = (data["source"], data["external_video_id"])
        existing = self.rows.get(key)
        if existing is not None:
            return Video(**existing), False
        row = {
            "id": uuid4(),
            **data,
            "processing_status": "pending",
            "processing_error": None,
            "processing_error_code": None,
            "processing_retryable": False,
        }
        self.rows[key] = row
        return Video(**row), True

    def get_by_id(self, video_id: UUID):
        row = next((row for row in self.rows.values() if row["id"] == video_id), None)
        return Video(**row) if row else None

    def get_by_source_external(self, source: str, external_video_id: str):
        row = self.rows.get((source, external_video_id))
        return Video(**row) if row else None

    def update_status(
        self,
        video_id: UUID,
        status: str,
        *,
        failure_code: str | None = None,
        retryable: bool = False,
        expected_status: str | None = None,
    ):
        for row in self.rows.values():
            if row["id"] == video_id:
                if expected_status is not None and row["processing_status"] != expected_status:
                    return None
                row["processing_status"] = status
                row["processing_error"] = None
                row["processing_error_code"] = failure_code
                row["processing_retryable"] = retryable
                self.status_history.append((status, failure_code, retryable))
                return Video(**row)
        return None


class FakeTranscripts:
    def __init__(self):
        self.rows = {}

    def upsert_track(self, data: dict):
        key = (data["video_id"], data["language_code"], data["source"])
        row = self.rows.get(key) or {"id": uuid4(), **data}
        row.update(data)
        self.rows[key] = row
        return VideoTranscript(**row)

    def list_for_video(self, video_id: UUID):
        return [VideoTranscript(**row) for row in self.rows.values() if row["video_id"] == str(video_id)]


class FakeSegments:
    def __init__(self):
        self.rows = {}

    def upsert_many(self, segments: list[dict]):
        for data in segments:
            key = (data["transcript_id"], data["sequence_number"])
            row = self.rows.get(key) or {"id": uuid4(), **data}
            row.update(data)
            self.rows[key] = row
        return sorted(
            [TranscriptSegment(**row) for row in self.rows.values()],
            key=lambda row: row.sequence_number,
        )

    def list_for_transcript(self, transcript_id: UUID):
        return [
            TranscriptSegment(**row)
            for row in self.rows.values()
            if row["transcript_id"] == str(transcript_id)
        ]


class FakeTranslations:
    def __init__(self):
        self.rows = {}

    def upsert_many(self, translations: list[dict]):
        for data in translations:
            self.rows[(data["transcript_segment_id"], data["language_code"])] = data
        return list(self.rows.values())


class FakeRomanizationSystems:
    def __init__(self):
        self.system = RomanizationSystem(
            id=UUID("44444444-4444-4444-4444-444444444444"),
            language_code="zh",
            code="pinyin",
            name="Pinyin",
            standard_status="official",
        )

    def get_by_language_and_code(self, language_code: str, code: str):
        return self.system if language_code == "zh" and code == "pinyin" else None


class FakeRomanizations:
    def __init__(self):
        self.rows = {}

    def upsert_many(self, romanizations: list[dict]):
        for data in romanizations:
            self.rows[(data["transcript_segment_id"], data["romanization_system_id"])] = data
        return list(self.rows.values())


def make_service():
    provider = FakeProvider()
    parts = {
        "channels": FakeChannels(),
        "videos": FakeVideos(),
        "transcripts": FakeTranscripts(),
        "segments": FakeSegments(),
        "translations": FakeTranslations(),
        "romanizations": FakeRomanizations(),
    }
    service = ContentIngestionService(
        video_provider=provider,
        transcript_provider=provider,
        romanization_provider=FakeRomanizationProvider(),
        normalizer=TranscriptNormalizer(),
        languages=FakeLanguages(),
        channels=parts["channels"],
        videos=parts["videos"],
        transcripts=parts["transcripts"],
        segments=parts["segments"],
        translations=parts["translations"],
        romanization_systems=FakeRomanizationSystems(),
        romanizations=parts["romanizations"],
    )
    return service, parts


def test_ingest_video_metadata_is_idempotent_and_preserves_channel():
    service, parts = make_service()

    first = service.ingest_video("https://youtube.com/watch?v=yt-123", target_language="en")
    second = service.ingest_video("https://youtube.com/watch?v=yt-123", target_language="en")

    assert first.video.id == second.video.id
    assert len(parts["videos"].rows) == 1
    assert len(parts["channels"].rows) == 1
    assert first.video.channel_id is not None
    assert first.video.processing_status == "transcript_ready"
    assert parts["videos"].status_history[:2] == [
        ("processing", None, False),
        ("transcript_ready", None, False),
    ]


def test_transcript_segments_are_rows_in_milliseconds_with_deterministic_order():
    service, parts = make_service()

    result = service.ingest_video("https://youtube.com/watch?v=yt-123")

    assert len(parts["transcripts"].rows) == 1
    assert len(parts["segments"].rows) == 2
    assert [segment.sequence_number for segment in result.segments] == [1, 2]
    assert [(segment.start_ms, segment.end_ms) for segment in result.segments] == [
        (0, 1000),
        (1500, 2000),
    ]
    assert result.segments[1].text == "第二句"


def test_multiple_transcript_tracks_can_coexist():
    service, parts = make_service()
    result = service.ingest_video("https://youtube.com/watch?v=yt-123")

    parts["transcripts"].upsert_track(
        {
            "video_id": str(result.video.id),
            "language_code": "en",
            "source": "caption_track",
            "is_original": False,
            "provider_metadata": {},
        }
    )

    assert len(parts["transcripts"].list_for_video(result.video.id)) == 2


def test_translations_and_romanizations_are_idempotent_and_linked():
    service, parts = make_service()

    first = service.ingest_video("https://youtube.com/watch?v=yt-123", target_language="en")
    second = service.ingest_video("https://youtube.com/watch?v=yt-123", target_language="en")

    assert first.translation_count == 2
    assert second.translation_count == 2
    assert len(parts["translations"].rows) == 2
    assert len(parts["romanizations"].rows) == 2
    for (_, language_code), row in parts["translations"].rows.items():
        assert language_code == "en"
        assert row["transcript_segment_id"]
    for (_, romanization_system_id), row in parts["romanizations"].rows.items():
        assert romanization_system_id == "44444444-4444-4444-4444-444444444444"
        assert row["transcript_segment_id"]


def test_normalizer_rejects_invalid_timestamps():
    normalizer = TranscriptNormalizer()

    try:
        normalizer.normalize(
            [SourceTranscriptSegment(start_seconds=1, duration_seconds=0, text="bad")]
        )
    except ValueError as exc:
        assert "timestamp" in str(exc).lower()
    else:
        raise AssertionError("Expected invalid timestamps to be rejected")


def test_transcript_failure_persists_only_safe_non_retryable_code():
    service, parts = make_service()

    def fail_transcript(external_video_id: str, language_code: str):
        raise SourceProviderError("Video này không có phụ đề.")

    service.transcript_provider.get_original_transcript = fail_transcript

    try:
        service.ingest_video("https://youtube.com/watch?v=yt-123")
    except ContentIngestionError as exc:
        assert exc.code == ContentProcessingFailureCode.TRANSCRIPT_UNAVAILABLE
        assert exc.retryable is False
    else:
        raise AssertionError("Expected transcript failure")

    video = next(iter(parts["videos"].rows.values()))
    assert video["processing_status"] == "failed"
    assert video["processing_error"] is None
    assert video["processing_error_code"] == "transcript_unavailable"
    assert video["processing_retryable"] is False


def test_unexpected_processing_failure_is_safe_and_retryable():
    service, parts = make_service()

    def fail_transcript(external_video_id: str, language_code: str):
        raise RuntimeError("provider secret must never be persisted")

    service.transcript_provider.get_original_transcript = fail_transcript

    try:
        service.ingest_video("https://youtube.com/watch?v=yt-123")
    except ContentIngestionError as exc:
        assert exc.code == ContentProcessingFailureCode.PROCESSING_FAILED
        assert exc.retryable is True
    else:
        raise AssertionError("Expected processing failure")

    video = next(iter(parts["videos"].rows.values()))
    assert video["processing_error"] is None
    assert video["processing_error_code"] == "processing_failed"
    assert "provider secret" not in str(video)


def test_ingestion_reads_each_romanization_system_once_for_all_segments():
    from unittest.mock import Mock

    service, _ = make_service()
    lookup = service.romanization_systems.get_by_language_and_code
    service.romanization_systems.get_by_language_and_code = Mock(wraps=lookup)
    service.ingest_video("https://youtube.com/watch?v=yt-123")
    service.romanization_systems.get_by_language_and_code.assert_called_once_with("zh", "pinyin")
