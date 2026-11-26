"""Ports the content module consumes."""
from __future__ import annotations

from typing import Protocol

from app.modules.content.domain.catalog import Language
from app.modules.content.domain.ingestion import SourceTranscriptTrack, SourceVideoMetadata
from app.modules.content.domain.knowledge import LLMLearningObjectEnrichment
from app.modules.content.domain.region_questions import LLMRegionQuestionSet


class SourceProviderError(Exception):
    """A content source (e.g. YouTube) rejected or failed a request; detail is source-provided text."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class UnsupportedSourceContent(SourceProviderError):
    """The video exists but is outside the configured bounds (length, visibility, language)."""


class SourceVideoUnavailable(SourceProviderError):
    """The source reports the video as missing or not publicly accessible."""


class ContentProviderFailure(Exception):
    """Typed external-provider failure carrying a safe Content failure code.

    Deliberately not a SourceProviderError, so no provider text is matched by markers.
    `code` is one of the existing Content failure codes; `transient` drives retry policy.
    """

    def __init__(self, code: str, *, transient: bool):
        super().__init__(code)
        self.code = code
        self.transient = transient


class LanguageCatalogReader(Protocol):
    def list_active(self) -> list[Language]: ...


class VideoSourceProvider(Protocol):
    def extract_external_video_id(self, url: str) -> str:
        ...

    def get_video_metadata(self, url: str) -> SourceVideoMetadata:
        ...


class TranscriptSourceProvider(Protocol):
    def get_original_transcript(self, external_video_id: str, language_code: str) -> SourceTranscriptTrack:
        ...

    def get_translated_transcript(
        self,
        external_video_id: str,
        target_language_code: str,
    ) -> SourceTranscriptTrack | None:
        ...


class RomanizationProvider(Protocol):
    def romanize(self, text: str, language_code: str) -> dict[str, str]:
        ...


class LearningObjectEnrichmentProvider(Protocol):
    provider_name: str
    model_name: str

    def enrich(self, prompt: str) -> LLMLearningObjectEnrichment:
        ...


class RegionQuestionProvider(Protocol):
    """M1 S6: proposes comprehension questions; the application validates every one."""

    provider_name: str
    model_name: str

    def generate(self, prompt: str) -> LLMRegionQuestionSet:
        ...
