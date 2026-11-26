from app.modules.content.domain.catalog import RomanizationSystem
from app.platform.persistence import V3Repository


class RomanizationSystemRepository(V3Repository):
    table_name = "romanization_systems"

    def get_by_language_and_code(
        self,
        language_code: str,
        code: str,
    ) -> RomanizationSystem | None:
        result = (
            self.table()
            .select("*")
            .eq("language_code", language_code)
            .eq("code", code)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return RomanizationSystem(**rows[0]) if rows else None

