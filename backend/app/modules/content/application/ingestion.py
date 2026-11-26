import logging
from uuid import UUID
from app.modules.content.domain.work_claims import ContentClaim, StaleContentClaim


from app.modules.content.domain.ingestion import (
    ContentIngestionResult,
    SourceTranscriptTrack,
    SourceVideoMetadata,
)
from app.modules.content.domain.library import ContentProcessingFailureCode
from app.modules.content.domain.catalog import TranscriptSegment, Video, VideoTranscript
from app.modules.content.domain.normalizer import TranscriptNormalizer, TranscriptNormalizationError

from app.modules.content.application.ports import (
    RomanizationProvider,
    SourceProviderError,
    SourceVideoUnavailable,
    TranscriptSourceProvider,
    UnsupportedSourceContent,
    VideoSourceProvider,
)
from app.modules.content.application.store_ports import (
    ChannelStore,
    LanguageStore,
    RomanizationSystemStore,
    SegmentRomanizationStore,
    SegmentTranslationStore,
    TranscriptSegmentStore,
    VideoStore,
    VideoTranscriptStore,
    VideoWorkIntentStore,
)

logger = logging.getLogger(__name__)


_FAILURE_MESSAGES = {
    ContentProcessingFailureCode.INVALID_VIDEO_URL: "Enter a valid YouTube video URL.",
    ContentProcessingFailureCode.VIDEO_UNAVAILABLE: "This YouTube video is unavailable.",
    ContentProcessingFailureCode.TRANSCRIPT_UNAVAILABLE: "A usable transcript is not available for this video.",
    ContentProcessingFailureCode.UNSUPPORTED_CONTENT: "This video is not supported for learning yet.",
    ContentProcessingFailureCode.PROCESSING_FAILED: "Video processing failed. Try again later.",
}


class ContentIngestionError(Exception):
    def __init__(
        self,
        code: ContentProcessingFailureCode,
        *,
        retryable: bool,
        status_code: int,
    ):
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.public_message = _FAILURE_MESSAGES[code]
        super().__init__(self.public_message)


class ContentIngestionService:
    def __init__(
        self,
        *,
        video_provider: VideoSourceProvider,
        transcript_provider: TranscriptSourceProvider,
        romanization_provider: RomanizationProvider,
        normalizer: TranscriptNormalizer,
        languages: LanguageStore,
        channels: ChannelStore,
        videos: VideoStore,
        transcripts: VideoTranscriptStore,
        segments: TranscriptSegmentStore,
        translations: SegmentTranslationStore,
        romanization_systems: RomanizationSystemStore,
        romanizations: SegmentRomanizationStore,
        work_intents: VideoWorkIntentStore | None = None,
    ):
        self.video_provider = video_provider
        self.transcript_provider = transcript_provider
        self.romanization_provider = romanization_provider
        self.normalizer = normalizer
        self.languages = languages
        self.channels = channels
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.translations = translations
        self.romanization_systems = romanization_systems
        self.romanizations = romanizations
        self.work_intents = work_intents

    def extract_external_video_id(self, url: str) -> str:
        try:
            return self.video_provider.extract_external_video_id(url)
        except (TypeError, ValueError) as exc:
            raise ContentIngestionError(
                ContentProcessingFailureCode.INVALID_VIDEO_URL,
                retryable=False,
                status_code=400,
            ) from exc

    def prepare_video(self, url: str) -> tuple[Video, bool]:
        external_video_id = self.extract_external_video_id(url)
        existing = self.videos.get_by_source_external("youtube", external_video_id)
        if existing is not None:
            return existing, False
        try:
            metadata = self.video_provider.get_video_metadata(url)
            self._require_supported_language(metadata.original_language_code)
        except ContentIngestionError:
            raise
        except SourceProviderError as exc:
            raise _provider_error(exc, transcript_stage=False) from exc
        except Exception as exc:
            logger.error("v3 video preparation failed external_video_id=%s", external_video_id, exc_info=True)
            raise ContentIngestionError(
                ContentProcessingFailureCode.PROCESSING_FAILED,
                retryable=True,
                status_code=503,
            ) from exc
        existing = self.videos.get_by_source_external(metadata.source, metadata.external_video_id)
        if existing is not None:
            return existing, False
        return self._persist_video(metadata)

    def ingest_video(self, url: str, target_language: str | None = None) -> ContentIngestionResult:
        video, _ = self.prepare_video(url)
        return self.process_video(video.id, target_language=target_language)

    def process_video(
        self,
        video_id: UUID,
        *,
        target_language: str | None = None,
        processing_already_claimed: bool = False,
        work_intent_id: UUID | None = None,
        execution_claim: ContentClaim | None = None,
    ) -> ContentIngestionResult:
        if work_intent_id is not None and execution_claim is None:
            raise RuntimeError("Async Content work requires fenced ownership")
        if execution_claim is not None and (
            execution_claim.intent_id != work_intent_id or execution_claim.video_id != video_id
            or execution_claim.stage != "transcript" or target_language is not None
        ):
            raise ValueError("Invalid transcript execution context")
        video = self.videos.get_by_id(video_id)
        if video is None:
            raise ContentIngestionError(
                ContentProcessingFailureCode.VIDEO_UNAVAILABLE,
                retryable=False,
                status_code=404,
            )
        try:
            self._require_supported_language(video.original_language_code)
            if target_language:
                self._require_supported_language(target_language)
            if not processing_already_claimed:
                video = self.videos.update_status(video.id, "processing") or video
            source_track = self.transcript_provider.get_original_transcript(
                video.external_video_id,
                video.original_language_code,
            )
            transcript, persisted_segments = self._persist_transcript(video, source_track)

            translation_count = 0
            if target_language and target_language != video.original_language_code:
                translated_track = self.transcript_provider.get_translated_transcript(
                    video.external_video_id,
                    target_language,
                )
                if translated_track:
                    translation_count = self._persist_translations(
                        persisted_segments,
                        translated_track,
                    )

            romanization_count = self._persist_romanizations(
                persisted_segments,
                video.original_language_code,
            )
            if work_intent_id is not None:
                if self.work_intents is None:
                    raise RuntimeError("Content work intent repository is unavailable")
                video, _ = self.work_intents.complete_transcript(execution_claim)
            else:
                video = self.videos.update_status(video.id, "transcript_ready") or video
            logger.info(
                "v3 content ingestion complete source=%s external_video_id=%s segments=%s translations=%s romanizations=%s",
                video.source,
                video.external_video_id,
                len(persisted_segments),
                translation_count,
                romanization_count,
            )
            return ContentIngestionResult(
                video=video,
                transcript=transcript,
                segments=persisted_segments,
                translation_count=translation_count,
                romanization_count=romanization_count,
            )
        except StaleContentClaim:
            raise
        except ContentIngestionError as exc:
            if execution_claim is None:
                self._mark_failed(video.id, exc)
            raise
        except SourceProviderError as exc:
            failure = _provider_error(exc, transcript_stage=True)
            if execution_claim is None:
                self._mark_failed(video.id, failure)
            raise failure from exc
        except (TranscriptNormalizationError, ValueError) as exc:
            failure = ContentIngestionError(
                ContentProcessingFailureCode.TRANSCRIPT_UNAVAILABLE,
                retryable=False,
                status_code=422,
            )
            if execution_claim is None:
                self._mark_failed(video.id, failure)
            raise failure from exc
        except Exception as exc:
            failure = ContentIngestionError(
                ContentProcessingFailureCode.PROCESSING_FAILED,
                retryable=True,
                status_code=503,
            )
            if execution_claim is None:
                self._mark_failed(video.id, failure)
            logger.error(
                "v3 content ingestion failed source=%s external_video_id=%s",
                video.source,
                video.external_video_id,
                exc_info=execution_claim is None,
            )
            raise failure from exc

    def _persist_video(self, metadata: SourceVideoMetadata) -> tuple[Video, bool]:
        channel_id = None
        if metadata.external_channel_id and metadata.channel_name:
            channel = self.channels.upsert_by_source_external(
                {
                    "source": metadata.source,
                    "external_channel_id": metadata.external_channel_id,
                    "channel_name": metadata.channel_name,
                    "channel_url": metadata.channel_url,
                    "metadata": {"provider": metadata.source},
                }
            )
            channel_id = str(channel.id)

        return self.videos.create_pending_by_source_external(
            {
                "source": metadata.source,
                "external_video_id": metadata.external_video_id,
                "channel_id": channel_id,
                "original_language_code": metadata.original_language_code,
                "title": metadata.title,
                "description": metadata.description,
                "thumbnail_url": metadata.thumbnail_url,
                "duration_ms": metadata.duration_ms,
                "published_at": metadata.published_at,
                "metadata": metadata.metadata | {"watch_url": metadata.watch_url},
            }
        )

    def _mark_failed(self, video_id: UUID, error: ContentIngestionError) -> None:
        self.videos.update_status(
            video_id,
            "failed",
            failure_code=error.code.value,
            retryable=error.retryable,
            expected_status="processing",
        )

    def _persist_transcript(
        self,
        video: Video,
        source_track: SourceTranscriptTrack,
    ) -> tuple[VideoTranscript, list[TranscriptSegment]]:
        normalized = self.normalizer.normalize(source_track.segments)
        if not normalized:
            raise ValueError("Transcript did not contain any valid text segments")
        transcript = self.transcripts.upsert_track(
            {
                "video_id": str(video.id),
                "language_code": source_track.language_code,
                "source": source_track.source,
                "is_original": source_track.is_original,
                "provider_metadata": source_track.provider_metadata | {"ingestion_status": "completed"},
            }
        )
        rows = [
            {
                "transcript_id": str(transcript.id),
                "sequence_number": segment.sequence_number,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
            }
            for segment in normalized
        ]
        return transcript, self.segments.upsert_many(rows)

    def _persist_translations(
        self,
        persisted_segments: list[TranscriptSegment],
        translated_track: SourceTranscriptTrack,
    ) -> int:
        normalized = self.normalizer.normalize(translated_track.segments)
        by_sequence = {segment.sequence_number: segment for segment in normalized}
        rows = []
        for segment in persisted_segments:
            translated = by_sequence.get(segment.sequence_number)
            if translated:
                rows.append(
                    {
                        "transcript_segment_id": str(segment.id),
                        "language_code": translated_track.language_code,
                        "text": translated.text,
                        "source": translated_track.source,
                        "provider_metadata": translated_track.provider_metadata,
                    }
                )
        return len(self.translations.upsert_many(rows))

    def _persist_romanizations(
        self,
        persisted_segments: list[TranscriptSegment],
        language_code: str,
    ) -> int:
        rows = []
        systems = {}
        for segment in persisted_segments:
            for system_code, text in self.romanization_provider.romanize(segment.text, language_code).items():
                if system_code not in systems:
                    systems[system_code] = self.romanization_systems.get_by_language_and_code(language_code, system_code)
                system = systems[system_code]
                if system and text.strip():
                    rows.append(
                        {
                            "transcript_segment_id": str(segment.id),
                            "romanization_system_id": str(system.id),
                            "text": text.strip(),
                            "source": "hybrid",
                        }
                    )
        return len(self.romanizations.upsert_many(rows))

    def _require_supported_language(self, code: str) -> None:
        if not self.languages.get_active(code):
            raise ContentIngestionError(
                ContentProcessingFailureCode.UNSUPPORTED_CONTENT,
                retryable=False,
                status_code=422,
            )


def _provider_error(exc: SourceProviderError, *, transcript_stage: bool) -> ContentIngestionError:
    # Typed source outcomes first; marker matching remains only for the caption adapter's text.
    if isinstance(exc, UnsupportedSourceContent):
        return ContentIngestionError(ContentProcessingFailureCode.UNSUPPORTED_CONTENT, retryable=False, status_code=422)
    if isinstance(exc, SourceVideoUnavailable):
        return ContentIngestionError(ContentProcessingFailureCode.VIDEO_UNAVAILABLE, retryable=False, status_code=422)
    detail = str(exc.detail or "").casefold()
    if any(marker in detail for marker in ("không khả dụng", "không tồn tại", "riêng tư", "unavailable", "private")):
        code = ContentProcessingFailureCode.VIDEO_UNAVAILABLE
        retryable = False
    elif transcript_stage and any(
        marker in detail
        for marker in ("phụ đề", "transcript", "caption", "disabled", "no transcript")
    ):
        code = ContentProcessingFailureCode.TRANSCRIPT_UNAVAILABLE
        retryable = False
    else:
        code = ContentProcessingFailureCode.PROCESSING_FAILED
        retryable = True
    return ContentIngestionError(
        code,
        retryable=retryable,
        status_code=(503 if retryable else 422),
    )
