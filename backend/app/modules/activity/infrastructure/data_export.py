"""Activity-module rows for the learner data export: the learning log and the study requests."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.platform.persistence import select_rows


class ActivityDataSection:
    name = "activity"

    def __init__(self, client: Any):
        self.client = client

    def export(self, user_id: UUID) -> dict[str, list[dict]]:
        log = select_rows(self.client, "learner_activity_log",
                          "id,language_code,kind,item_type,item_id,source_type,source_id,outcome,score,detail,"
                          "occurred_at", filters={"user_id": str(user_id)})
        requests = select_rows(self.client, "learner_study_requests",
                               "id,language_code,kind,item_type,item_id,reason,status,created_by,created_at,closed_at",
                               filters={"user_id": str(user_id)})
        return {"activity_log": log, "study_requests": requests}
