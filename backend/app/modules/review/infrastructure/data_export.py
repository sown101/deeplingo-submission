"""Review-module rows for the learner data export: what is scheduled and the review history.
Internal FSRS parameters (stability, difficulty, state snapshots) are not exported."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.platform.persistence import select_rows


class ReviewDataSection:
    name = "review"

    def __init__(self, client: Any):
        self.client = client

    def export(self, user_id: UUID) -> dict[str, list[dict]]:
        states = select_rows(self.client, "review_states",
                             "id,concept_id,review_mode,due_at,reps,lapses,last_reviewed_at,created_at",
                             filters={"user_id": str(user_id)})
        events = select_rows(self.client, "review_events", "review_state_id,review_mode,rating,reviewed_at",
                             filters={}, in_filter=("review_state_id", [state["id"] for state in states]))
        return {"review_states": states, "review_events": events}
