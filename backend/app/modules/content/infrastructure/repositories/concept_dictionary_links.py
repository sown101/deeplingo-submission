from uuid import UUID

from app.modules.content.domain.knowledge import ConceptDictionaryLink
from app.platform.persistence import V3Repository


class ConceptDictionaryLinkRepository(V3Repository):
    table_name = "concept_dictionary_links"

    def list_for_concept(self, concept_id: UUID) -> list[ConceptDictionaryLink]:
        result = self.table().select("*").eq("concept_id", str(concept_id)).execute()
        return [ConceptDictionaryLink(**row) for row in (result.data or [])]

    def get_by_ids(self, concept_id: UUID, dictionary_entry_id: UUID) -> ConceptDictionaryLink | None:
        result = (
            self.table()
            .select("*")
            .eq("concept_id", str(concept_id))
            .eq("dictionary_entry_id", str(dictionary_entry_id))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return ConceptDictionaryLink(**rows[0]) if rows else None

    def upsert_link(
        self,
        *,
        concept_id: UUID,
        dictionary_entry_id: UUID,
        relation_type: str = "supports",
    ) -> ConceptDictionaryLink:
        result = (
            self.table()
            .upsert(
                {
                    "concept_id": str(concept_id),
                    "dictionary_entry_id": str(dictionary_entry_id),
                    "relation_type": relation_type,
                },
                on_conflict="concept_id,dictionary_entry_id",
            )
            .execute()
        )
        return ConceptDictionaryLink(**result.data[0])
