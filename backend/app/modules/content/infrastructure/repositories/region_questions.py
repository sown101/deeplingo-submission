from uuid import UUID

from app.modules.content.domain.region_questions import RegionQuestion
from app.platform.persistence import V3Repository


class RegionQuestionRepository(V3Repository):
    """M1 S6 region questions (service role only). Writes happen only in the fenced worker RPC."""

    table_name = "region_questions"

    def list_for_region(self, region_preparation_id: UUID) -> list[RegionQuestion]:
        result = (
            self.table().select("*")
            .eq("region_preparation_id", str(region_preparation_id))
            .order("position").execute()
        )
        return [RegionQuestion(**row) for row in result.data or []]
