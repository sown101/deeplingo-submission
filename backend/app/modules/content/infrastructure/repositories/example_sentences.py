"""Example sentences (`example_sentences`): shared content, service-role access only."""
from __future__ import annotations

from uuid import UUID

from app.modules.content.domain.example_sentences import ExampleSentence
from app.platform.persistence import IN_CHUNK, V3Repository

MAX_LISTED = 12


class ExampleSentenceRepository(V3Repository):
    table_name = "example_sentences"

    def list_for_concept(self, concept_id: UUID) -> list[ExampleSentence]:
        rows = (
            self.table().select("*").eq("concept_id", str(concept_id))
            .order("created_at").limit(MAX_LISTED).execute().data or []
        )
        return [ExampleSentence(**row) for row in rows]

    def list_for_concepts(self, concept_ids: list[UUID]) -> dict[UUID, list[ExampleSentence]]:
        """Keep the per-concept limit and ordering in PostgREST's embedded query."""
        ids = list(dict.fromkeys(str(concept_id) for concept_id in concept_ids))
        examples = {}
        for start in range(0, len(ids), IN_CHUNK):
            rows = (
                self.client.schema("v3").table("concepts").select("id,example_sentences(*)")
                .in_("id", ids[start:start + IN_CHUNK])
                .order("created_at", foreign_table=self.table_name)
                .limit(MAX_LISTED, foreign_table=self.table_name).execute().data or []
            )
            examples.update({UUID(row["id"]): [ExampleSentence(**item) for item in row[self.table_name]]
                             for row in rows})
        return examples

    def add(self, sentence: ExampleSentence) -> ExampleSentence:
        """Idempotent: the same sentence of the same kind for a Concept is stored once."""
        data = sentence.model_dump(mode="json", exclude_none=True, exclude={"id", "created_at"})
        self.table().upsert(data, on_conflict="concept_id,source_kind,text_key", ignore_duplicates=True).execute()
        rows = (
            self.table().select("*").eq("concept_id", str(sentence.concept_id))
            .eq("source_kind", sentence.source_kind.value).eq("text_key", sentence.text_key)
            .limit(1).execute().data or []
        )
        return ExampleSentence(**rows[0])
