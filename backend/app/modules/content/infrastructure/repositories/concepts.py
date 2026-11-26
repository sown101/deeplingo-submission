from app.modules.content.domain.knowledge import Concept
from app.platform.persistence import V3Repository, cached_read


class ConceptRepository(V3Repository):
    table_name = "concepts"

    @cached_read
    def list_by_ids(self, concept_ids: list) -> list[Concept]:
        if not concept_ids:
            return []
        result = self.table().select("*").in_("id", [str(item) for item in concept_ids]).execute()
        return [Concept(**row) for row in (result.data or [])]

    @cached_read
    def get_by_id(self, concept_id) -> Concept | None:
        result = self.table().select("*").eq("id", str(concept_id)).limit(1).execute()
        rows = result.data or []
        return Concept(**rows[0]) if rows else None

    def find_by_identity(
        self,
        *,
        language_code: str,
        concept_type: str,
        normalized_text: str,
        sense_key: str,
    ) -> Concept | None:
        result = (
            self.table()
            .select("*")
            .eq("language_code", language_code)
            .eq("type", concept_type)
            .eq("normalized_text", normalized_text)
            .eq("sense_key", sense_key)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return Concept(**rows[0]) if rows else None

    def upsert_by_identity(self, data: dict) -> Concept:
        result = (
            self.table()
            .upsert(data, on_conflict="language_code,type,normalized_text,sense_key")
            .execute()
        )
        return Concept(**result.data[0])

    def sample_sense_glosses(self, *, language_code: str, limit: int = 200) -> list[tuple[str, str]]:
        """(normalized_text, sense gloss) of dictionary-sense Concepts, for wrong answer options."""
        rows = (
            self.table().select("normalized_text,metadata").eq("language_code", language_code)
            .in_("type", ["vocabulary", "expression"]).limit(limit).execute().data or []
        )
        return [
            (row["normalized_text"], row["metadata"]["sense_gloss"]) for row in rows
            if isinstance(row.get("metadata"), dict) and isinstance(row["metadata"].get("sense_gloss"), str)
        ]
