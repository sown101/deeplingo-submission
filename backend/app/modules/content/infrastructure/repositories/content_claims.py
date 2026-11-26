"""Claim-scoped persistence. Each RPC locks ownership AND writes in one transaction."""

from app.modules.content.domain.work_claims import ContentClaim, StaleContentClaim
from app.modules.content.domain.knowledge import Concept, LearningObject, ConceptDictionaryLink
from app.modules.content.domain.catalog import (
    VideoTranscript,
    TranscriptSegment,
    SegmentRomanization,
)
from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
from app.modules.content.infrastructure.repositories.learning_objects import (
    LearningObjectRepository,
)
from app.modules.content.infrastructure.repositories.video_transcripts import (
    VideoTranscriptRepository,
)
from app.modules.content.infrastructure.repositories.transcript_segments import (
    TranscriptSegmentRepository,
)
from app.modules.content.infrastructure.repositories.segment_romanizations import (
    SegmentRomanizationRepository,
)
from app.modules.content.infrastructure.repositories.concept_dictionary_links import (
    ConceptDictionaryLinkRepository,
)
from app.modules.content.infrastructure.repositories.dictionary_entries import (
    DictionaryEntryRepository,
)


def claim_parameters(claim: ContentClaim) -> dict:
    return {"p_intent_id": str(claim.intent_id), "p_claim_token": str(claim.token),
            "p_claim_epoch": claim.epoch}


def fenced_rpc(client, name: str, claim: ContentClaim, **parameters):
    scoped = client.schema("v3") if hasattr(client, "schema") else client
    try:
        result = scoped.rpc(name, claim_parameters(claim) | parameters).execute()
    except Exception as exc:
        if str(getattr(exc, "code", "")) == "DL001":
            raise StaleContentClaim("Content execution ownership lost") from exc
        raise
    return result.data


class ClaimedTranscripts(VideoTranscriptRepository):
    def __init__(self, client, claim):
        super().__init__(client)
        self.claim = claim

    def upsert_track(self, data):
        return VideoTranscript(**fenced_rpc(self.client, "write_claimed_transcript_track", self.claim, p_track=data))


class ClaimedSegments(TranscriptSegmentRepository):
    def __init__(self, client, claim):
        super().__init__(client)
        self.claim = claim

    def upsert_many(self, segments):
        if not segments:
            return []
        rows = fenced_rpc(self.client, "write_claimed_transcript_segments", self.claim, p_segments=segments)
        return sorted([TranscriptSegment(**row) for row in rows], key=lambda row: row.sequence_number)


class ClaimedRomanizations(SegmentRomanizationRepository):
    def __init__(self, client, claim):
        super().__init__(client)
        self.claim = claim

    def upsert_many(self, romanizations):
        if not romanizations:
            return []
        rows = fenced_rpc(self.client, "write_claimed_segment_romanizations", self.claim, p_romanizations=romanizations)
        return [SegmentRomanization(**row) for row in rows]


class ClaimedConcepts(ConceptRepository):
    def __init__(self, client, claim):
        super().__init__(client)
        self.claim = claim

    def upsert_by_identity(self, data):
        return Concept(**fenced_rpc(self.client, "resolve_claimed_concept", self.claim, p_concept=data))


class ClaimedLearningObjects(LearningObjectRepository):
    def __init__(self, client, claim):
        super().__init__(client)
        self.claim = claim

    def upsert_by_occurrence(self, data):
        return LearningObject(**fenced_rpc(self.client, "resolve_claimed_occurrence", self.claim, p_occurrence=data))

    def update_enrichment(self, learning_object_id, data):
        # Send ONLY this language's new value, never a worker's old JSONB snapshot.
        enrichment = data["raw_ai_diagnostics"]["enrichment"]
        return LearningObject(**fenced_rpc(
            self.client, "enrich_claimed_occurrence", self.claim,
            p_learning_object_id=str(learning_object_id), p_enrichment=enrichment,
        ))

    def record_sense_review(self, learning_object_id, *, target_language_code, review, raw_ai_diagnostics):
        # A26: send ONLY this language and its review; the database merges them into the locked row.
        return LearningObject(**fenced_rpc(
            self.client, "record_claimed_sense_review", self.claim,
            p_learning_object_id=str(learning_object_id), p_target_language_code=target_language_code,
            p_review=review,
        ))


class ClaimedDictionaryEntries(DictionaryEntryRepository):
    def upsert_by_lookup(self, data):
        # The async factory uses NoopDictionaryProvider. New reference creation
        # is not part of this execution contract; fail closed if wiring changes.
        raise RuntimeError("Async preparation cannot mutate dictionary reference")


class ClaimedConceptLinks(ConceptDictionaryLinkRepository):
    def __init__(self, client, claim):
        super().__init__(client)
        self.claim = claim

    def upsert_link(self, *, concept_id, dictionary_entry_id, relation_type="supports"):
        return ConceptDictionaryLink(**fenced_rpc(
            self.client, "link_claimed_concept_reference", self.claim,
            p_concept_id=str(concept_id), p_dictionary_entry_id=str(dictionary_entry_id),
            p_relation_type=relation_type,
        ))


class ClaimedRegionQuestions:
    """M1 S6: replaces the claimed region's questions and records their status in one RPC."""

    def __init__(self, client, claim):
        self.client = client
        self.claim = claim

    def write(self, *, status: str, questions: list[dict]) -> int:
        return int(fenced_rpc(self.client, "write_claimed_region_questions", self.claim,
                              p_status=status, p_questions=questions) or 0)
