from uuid import UUID

from app.platform.persistence import V3Repository


class ConceptImageRepository(V3Repository):
    table_name = "concept_images"

    def list_for(self, concept_ids: list[UUID]) -> list[dict]:
        if not concept_ids:
            return []
        return self.table().select("*").in_("concept_id", [str(item) for item in concept_ids]).execute().data or []

    def save(self, row: dict) -> None:
        self.table().upsert(row, on_conflict="concept_id").execute()
