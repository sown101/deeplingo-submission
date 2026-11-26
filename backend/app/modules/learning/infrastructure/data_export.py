"""Learning-module rows for the learner data export: speaking sessions, daily study plans with their
proposals, looked-up words and what the agent remembers. Practice and speaking activity are in the learning
log section."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.platform.persistence import select_optional_rows, select_rows


class LearningDataSection:
    name = "learning"

    def __init__(self, client: Any):
        self.client = client

    def export(self, user_id: UUID) -> dict[str, list[dict]]:
        plans = select_rows(self.client, "companion_plans", "id,language_code,plan_day,intro,created_at",
                            filters={"user_id": str(user_id)})
        proposals = select_rows(self.client, "companion_proposals",
                                "id,plan_id,position,kind,library_item_id,video_title,companion_entry,item_count,"
                                "minutes,reason,status,decided_at,created_at",
                                filters={"user_id": str(user_id)})
        speaking = select_rows(self.client, "speaking_sessions",
                               "id,language_code,library_item_id,status,targets,events,occurred_at,created_at",
                               filters={"user_id": str(user_id)})
        memory = select_optional_rows(self.client, "learner_agent_memory", "id,language_code,kind,text,created_at",
                                      filters={"user_id": str(user_id)})
        return {"speaking_sessions": speaking, "agent_memory": memory, "study_plans": plans,
                "study_plan_proposals": proposals}
