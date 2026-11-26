from app.modules.content.domain.catalog import Language
from app.platform.persistence import V3Repository


class LanguageRepository(V3Repository):
    table_name = "languages"

    def get_active(self, code: str) -> Language | None:
        result = (
            self.table()
            .select("code,name_en,name_native,script,is_active,display_order")
            .eq("code", code)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return Language(**rows[0]) if rows else None

    def list_active(self) -> list[Language]:
        result = (
            self.table()
            .select("code,name_en,name_native,script,is_active,display_order")
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [Language(**row) for row in (result.data or [])]
