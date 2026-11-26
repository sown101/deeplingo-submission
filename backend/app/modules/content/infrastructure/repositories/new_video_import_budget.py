"""O12 ledger of new-video imports per learner (`learner_new_video_imports`): service-role access only."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.modules.content.application.library import ImportBudgetDecision
from app.platform.persistence import V3Repository


class NewVideoImportBudgetRepository(V3Repository):
    table_name = "learner_new_video_imports"

    def __init__(self, client, *, limit: int, window_seconds: int):
        super().__init__(client)
        self.limit = limit
        self.window_seconds = window_seconds

    def charge(self, *, user_id: UUID, video_id: UUID) -> ImportBudgetDecision:
        """Atomic in the database: counts the rolling window and records the charge once per video."""
        result = self.client.schema(self.schema).rpc("charge_new_video_import", {
            "p_user_id": str(user_id), "p_video_id": str(video_id),
            "p_limit": self.limit, "p_window_seconds": self.window_seconds,
        }).execute()
        row = result.data[0] if isinstance(result.data, list) and result.data else result.data
        if not isinstance(row, dict) or not isinstance(row.get("allowed"), bool):
            raise RuntimeError("New-video budget returned no decision")
        reset_at = row.get("reset_at")
        return ImportBudgetDecision(
            allowed=row["allowed"], charged=bool(row.get("charged")), used=int(row.get("used") or 0),
            limit=int(row.get("limit") or self.limit),
            reset_at=datetime.fromisoformat(reset_at) if isinstance(reset_at, str) else None,
        )
