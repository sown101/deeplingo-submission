"""Read-only projection of the learner's learned items for speaking hints.

Items come only from prepared occurrences in the learner's own Library videos,
so every hint is trusted content the learner has already met. Practiced items
(with assessed mastery samples) rank first. Nothing here writes learner state.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.content.contracts import prepared_context


@dataclass(frozen=True)
class LearnedItem:
    concept_id: str
    text: str
    kind: str
    meaning: str | None
    source: str  # "practiced" | "from_video"
    forms: tuple[str, ...]


class LearnedItemCatalog:
    def __init__(self, *, library, videos, learning_objects, concepts):
        self.library = library
        self.videos = videos
        self.learning_objects = learning_objects
        self.concepts = concepts

    def for_learner(
        self, user_id: UUID, *, language_code: str, support_language_code: str | None,
        limit: int = 40, max_videos: int = 8, video_ids: set[UUID] | None = None,
        owned_videos: list | None = None, segment_ids: set[UUID] | None = None,
    ) -> list[LearnedItem]:
        """``owned_videos``: videos the caller already resolved through the learner's Library.

        Without it the Library is listed here. Either way only ready videos in the learning
        language are read, and reads are batched (one query per table) to keep latency flat.
        ``segment_ids`` keeps only occurrences in those transcript segments (a study region the
        caller resolved through the Library and the current transcript); such a region needs its own
        prepared occurrences, not the whole video's preparation (M1 S7b), so the video's
        ``learning_status`` is not required then.
        """
        if owned_videos is None:
            candidates = [association.video_id for association in self.library.list_for_user(user_id, limit=50)
                          if video_ids is None or association.video_id in video_ids]
            by_id = self.videos.get_many_by_ids(list(dict.fromkeys(candidates)))
            owned_videos = [by_id[video_id] for video_id in dict.fromkeys(candidates) if video_id in by_id]
        videos = [video for video in owned_videos
                  if video.original_language_code == language_code
                  and (segment_ids is not None or video.learning_status == "ready")][:max_videos]

        forms: dict[str, list[str]] = {}
        meanings: dict[str, str] = {}
        recency: dict[str, int] = {}
        diagnostics: dict[str, list[dict | None]] = {}
        occurrences: dict[UUID, list] = {}
        for occurrence in self.learning_objects.list_for_videos([video.id for video in videos]):
            if segment_ids is not None and occurrence.transcript_segment_id not in segment_ids:
                continue
            occurrences.setdefault(occurrence.video_id, []).append(occurrence)
        for rank, video in enumerate(videos):
            for occurrence in occurrences.get(video.id, []):
                concept_id = str(occurrence.concept_id)
                recency.setdefault(concept_id, rank)
                text = (occurrence.evidence_text or "").strip()
                if text and text not in forms.setdefault(concept_id, []):
                    forms[concept_id].append(text)
                diagnostics.setdefault(concept_id, []).append(occurrence.raw_ai_diagnostics)
        if not forms:
            return []

        concepts = {
            str(concept.id): concept
            for concept in self.concepts.list_by_ids([UUID(item) for item in forms])
            if concept.id is not None and concept.language_code == language_code
        }
        for concept_id, concept in concepts.items():
            for raw in diagnostics.get(concept_id, []):
                context = prepared_context(
                    raw, concept_id=concept_id, sense_key=concept.sense_key,
                    source_language_code=language_code, support_language_code=support_language_code,
                )
                if context is not None:
                    meanings[concept_id] = context["contextual_meaning"].strip()
                    break

        def order(concept_id: str):
            return recency.get(concept_id, 99)

        items = []
        for concept_id in sorted(concepts, key=order)[:limit]:
            concept = concepts[concept_id]
            canonical = concept.canonical_text.strip()
            variants = [canonical, *forms.get(concept_id, [])]
            items.append(LearnedItem(
                concept_id=concept_id,
                text=canonical,
                kind=concept.type.value if hasattr(concept.type, "value") else str(concept.type),
                meaning=meanings.get(concept_id),
                source="from_video",
                forms=tuple(dict.fromkeys(form for form in variants if form))[:4],
            ))
        return items
