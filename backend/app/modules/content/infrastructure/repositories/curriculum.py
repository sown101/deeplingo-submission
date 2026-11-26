from typing import Any

from app.modules.content.domain.extraction import GrammarCatalogueItem
from app.platform.persistence import V3Repository


class CurriculumRepository(V3Repository):
    """Curriculum levels; a level is replaced only through the atomic load RPC."""

    table_name = "curriculum_levels"

    def content_hash(self, *, language_code: str, framework: str, level: str) -> str | None:
        result = (
            self.table()
            .select("content_hash")
            .eq("language_code", language_code)
            .eq("framework", framework)
            .eq("level", level)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0]["content_hash"] if rows else None

    def load_level(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.schema(self.schema).rpc("load_curriculum_level", {"p_level": payload}).execute().data


class GrammarPointRepository(V3Repository):
    """Grammar catalogue offered to extraction: every loaded point of the language."""

    table_name = "grammar_points"

    def for_keys(self, *, language_code: str, keys: list[str]) -> list[dict]:
        if not keys:
            return []
        return (self.table().select("key,title,pattern,explanation")
                .eq("language_code", language_code).in_("key", keys).order("key").limit(3).execute()).data or []

    def catalogue_for_language(self, language_code: str) -> list[GrammarCatalogueItem]:
        result = (
            self.table()
            .select("key,title,pattern,forms")
            .eq("language_code", language_code)
            .order("key")
            .limit(500)
            .execute()
        )
        return [GrammarCatalogueItem(**{**row, "forms": tuple(row.get("forms") or ())})
                for row in (result.data or [])]
