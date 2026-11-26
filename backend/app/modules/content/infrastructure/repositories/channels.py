from uuid import UUID

from app.modules.content.domain.catalog import Channel
from app.platform.persistence import V3Repository


class ChannelRepository(V3Repository):
    table_name = "channels"

    def upsert_by_source_external(self, data: dict) -> Channel:
        result = (
            self.table()
            .upsert(data, on_conflict="source,external_channel_id")
            .execute()
        )
        return Channel(**result.data[0])

    def get_by_id(self, channel_id: UUID) -> Channel | None:
        result = self.table().select("*").eq("id", str(channel_id)).limit(1).execute()
        rows = result.data or []
        return Channel(**rows[0]) if rows else None

