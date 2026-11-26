from pypinyin import Style as PinyinStyle
from pypinyin import lazy_pinyin

from app.modules.content.domain.ingestion import (
    SourceTranscriptSegment,
    SourceTranscriptTrack,
    SourceVideoMetadata,
)
from app.modules.content.domain.pinyin import HANYU_PINYIN
from app.modules.content.infrastructure.youtube import YouTubeService
from app.platform.process_clients import ProcessClientCache

try:
    import cutlet as _cutlet_module

    _CUTLET = ProcessClientCache(_cutlet_module.Cutlet)
except Exception:
    _CUTLET = None


class YouTubeContentProvider:
    source = "youtube"

    def __init__(self, youtube: YouTubeService | None = None):
        self.youtube = youtube or YouTubeService()

    def extract_external_video_id(self, url: str) -> str:
        return self.youtube.extract_video_id(url)

    def get_video_metadata(self, url: str) -> SourceVideoMetadata:
        external_video_id = self.extract_external_video_id(url)
        metadata = self.youtube.get_video_metadata(url)
        original_language = self.youtube.detect_video_language(external_video_id)
        return SourceVideoMetadata(
            source=self.source,
            external_video_id=external_video_id,
            watch_url=metadata.get("watch_url") or f"https://www.youtube.com/watch?v={external_video_id}",
            title=metadata.get("title") or "Unknown Title",
            description=metadata.get("description") or None,
            thumbnail_url=metadata.get("thumbnail"),
            duration_ms=(int(metadata["duration"] * 1000) if metadata.get("duration") else None),
            original_language_code=original_language,
            external_channel_id=metadata.get("uploader_url") or metadata.get("uploader") or "unknown",
            channel_name=metadata.get("uploader") or "Unknown Channel",
            channel_url=metadata.get("uploader_url"),
            metadata={
                "iframe_url": metadata.get("iframe_url"),
                "watch_url": metadata.get("watch_url"),
                "provider": "youtube_oembed",
            },
        )

    def get_original_transcript(self, external_video_id: str, language_code: str) -> SourceTranscriptTrack:
        raw = self.youtube.get_transcript_detailed(
            external_video_id,
            languages=self._language_priority(language_code),
        )
        return self._track_from_raw(raw, language_code=language_code, is_original=True)

    def get_translated_transcript(
        self,
        external_video_id: str,
        target_language_code: str,
    ) -> SourceTranscriptTrack | None:
        available = self.youtube.list_available_transcripts(external_video_id)
        matched = next(
            (
                item["language_code"]
                for item in available
                if item["language_code"] == target_language_code
                or item["language_code"].startswith(f"{target_language_code}-")
            ),
            None,
        )
        if not matched:
            return None
        raw = self.youtube.get_transcript_detailed(external_video_id, languages=[matched])
        return self._track_from_raw(
            raw,
            language_code=target_language_code,
            is_original=False,
            provider_metadata={"source_language_code": matched},
        )

    def _track_from_raw(
        self,
        raw: list[dict],
        *,
        language_code: str,
        is_original: bool,
        provider_metadata: dict | None = None,
    ) -> SourceTranscriptTrack:
        segments = [
            SourceTranscriptSegment(
                sequence_number=item.get("sequence_number"),
                start_seconds=float(item.get("start") or 0),
                duration_seconds=float(item.get("duration") or 0),
                text=item.get("text") or "",
            )
            for item in raw
        ]
        return SourceTranscriptTrack(
            language_code=language_code,
            source="caption_track",
            is_original=is_original,
            provider_metadata=provider_metadata or {},
            segments=segments,
        )

    def _language_priority(self, language_code: str) -> list[str]:
        lang = (language_code or "en").lower()
        if lang == "zh":
            return ["zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en"]
        if lang == "ja":
            return ["ja", "en"]
        if lang == "ko":
            return ["ko", "en"]
        if lang == "vi":
            return ["vi", "en"]
        return ["en", "en-US", "en-GB"]


class LocalRomanizationProvider:
    def romanize(self, text: str, language_code: str) -> dict[str, str]:
        if language_code == "zh":
            tokens = lazy_pinyin(text, style=PinyinStyle.TONE)
            return {HANYU_PINYIN: " ".join(token for token in tokens if token.strip())}
        if language_code == "ja" and _CUTLET is not None:
            try:
                engine = _CUTLET.get()
            except Exception:
                # Preserve optional native-tokenizer unavailability behavior.
                return {}
            return {"romaji": engine.romanize(text)}
        return {}
