import re

from app.modules.content.domain.ingestion import (
    NormalizedTranscriptSegment,
    SourceTranscriptSegment,
)


class TranscriptNormalizationError(ValueError):
    pass


class TranscriptNormalizer:
    def normalize(
        self,
        segments: list[SourceTranscriptSegment],
    ) -> list[NormalizedTranscriptSegment]:
        normalized: list[NormalizedTranscriptSegment] = []
        seen: set[tuple[int, int, str]] = set()

        ordered = sorted(
            enumerate(segments, start=1),
            key=lambda item: (
                item[1].sequence_number if item[1].sequence_number is not None else item[0],
                item[1].start_seconds,
            ),
        )

        for fallback_sequence, segment in ordered:
            text = self._normalize_text(segment.text)
            if not text:
                continue
            if segment.start_seconds < 0 or segment.duration_seconds <= 0:
                raise TranscriptNormalizationError("Invalid transcript timestamp")

            start_ms = round(segment.start_seconds * 1000)
            end_ms = round((segment.start_seconds + segment.duration_seconds) * 1000)
            if end_ms <= start_ms:
                raise TranscriptNormalizationError("Transcript segment end must be after start")

            key = (start_ms, end_ms, text)
            if key in seen:
                continue
            seen.add(key)

            normalized.append(
                NormalizedTranscriptSegment(
                    sequence_number=segment.sequence_number or fallback_sequence,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )

        normalized.sort(key=lambda item: (item.sequence_number, item.start_ms, item.end_ms))
        for index, segment in enumerate(normalized, start=1):
            segment.sequence_number = index
        return normalized

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()

