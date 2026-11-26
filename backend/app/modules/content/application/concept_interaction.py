"""Authorize and project a persisted Concept in one exact LearningObject context."""

from uuid import UUID

from pydantic import ValidationError

from app.modules.identity.contracts import CurrentUser
from app.modules.content.application.concept_interaction_views import ConceptInteractionView, DictionarySenseView
from app.modules.content.domain.dictionary_sources import DICTIONARY_SOURCES
from app.modules.content.domain.prepared_context import prepared_context


class ConceptInteractionError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def _not_found() -> ConceptInteractionError:
    return ConceptInteractionError(
        "Concept occurrence not found.", status_code=404, code="concept_occurrence_not_found",
    )


def _context_unavailable() -> ConceptInteractionError:
    return ConceptInteractionError(
        "This explanation is not ready yet.", status_code=409, code="concept_context_unavailable",
    )


class ConceptInteractionService:
    def __init__(self, *, library, learning_objects, segments, transcripts, concepts, preferences):
        self.library = library
        self.learning_objects = learning_objects
        self.segments = segments
        self.transcripts = transcripts
        self.concepts = concepts
        self.preferences = preferences

    def get(self, user: CurrentUser, library_item_id: UUID, learning_object_id: UUID) -> ConceptInteractionView:
        # The service-role repositories may bypass RLS. Establish ownership
        # before reading the requested LearningObject, and never reveal which
        # half of an inaccessible/missing path failed.
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        if association is None:
            raise _not_found()
        learning_object = self.learning_objects.get_by_id(learning_object_id)
        if learning_object is None or learning_object.video_id != association.video_id:
            raise _not_found()
        segment = self.segments.get_by_id(learning_object.transcript_segment_id)
        if segment is None:
            raise _not_found()
        transcript = self.transcripts.get_by_id(segment.transcript_id)
        concept = self.concepts.get_by_id(learning_object.concept_id)
        if (transcript is None or concept is None or concept.id is None
                or transcript.video_id != association.video_id
                or concept.language_code != transcript.language_code):
            raise _not_found()
        start, end = learning_object.start_codepoint, learning_object.end_codepoint
        if (start is None or end is None or not 0 <= start < end <= len(segment.text)
                or segment.text[start:end] != learning_object.evidence_text):
            raise _not_found()

        preference = self.preferences.get_by_language_for_user(
            user_id=user.id, language_code=transcript.language_code,
        )
        support_language = preference.support_language_code if preference else None
        if not support_language:
            raise ConceptInteractionError(
                "Set a support language to view this explanation.",
                status_code=409, code="support_language_unavailable",
            )

        enrichment = prepared_context(
            learning_object.raw_ai_diagnostics,
            concept_id=str(concept.id), sense_key=concept.sense_key,
            source_language_code=transcript.language_code,
            support_language_code=support_language,
        )
        if enrichment is None:
            raise _context_unavailable()
        try:
            return ConceptInteractionView(
                library_item_id=library_item_id,
                learning_object_id=learning_object_id,
                expression=concept.canonical_text,
                occurrence_text=learning_object.evidence_text,
                source_segment_text=segment.text,
                start_codepoint=start,
                end_codepoint=end,
                learning_language_code=transcript.language_code,
                support_language_code=support_language,
                contextual_meaning=enrichment["contextual_meaning"],
                explanation=enrichment.get("explanation"),
                **meaning_source(enrichment),
            )
        except ValidationError as exc:
            raise _context_unavailable() from exc


def meaning_source(enrichment: dict) -> dict:
    """Learner-facing provenance of a prepared meaning.

    Only a meaning translated from a sense of a registered, credited dictionary is shown as
    "dictionary"; anything else, including items prepared before prompt v2, is "unverified".
    """
    sense = enrichment.get("dictionary_sense")
    source = DICTIONARY_SOURCES.get(sense.get("provider")) if isinstance(sense, dict) else None
    if (enrichment.get("meaning_provenance") != "translated_from_sense" or source is None
            or not isinstance(sense.get("headword"), str) or not isinstance(sense.get("text"), str)):
        return {"meaning_provenance": "unverified", "dictionary_sense": None}
    return {
        "meaning_provenance": "dictionary",
        "dictionary_sense": DictionarySenseView(
            headword=sense["headword"][:500],
            reading=_clip(sense.get("reading"), 200),
            part_of_speech=_clip(sense.get("pos"), 50),
            definition=_clip(sense["text"], 1000) or sense["headword"][:500],
            source_name=source.name,
            source_url=source.entry_url(sense["headword"]),
            license_name=source.license_name,
            license_url=source.license_url,
        ),
    }


def _clip(value, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
