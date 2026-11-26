"""Practice-module rows for the learner data export: grammar progress per point."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.platform.persistence import select_rows


class PracticeDataSection:
    name = "practice"

    def __init__(self, client: Any):
        self.client = client

    def export(self, user_id: UUID) -> dict[str, list[dict]]:
        return {"grammar_progress": select_rows(
            self.client, "learner_grammar_progress",
            "language_code,grammar_key,lesson_learned_at,attempts,correct_count,last_attempt_at,last_correct_at,"
            "updated_at", filters={"user_id": str(user_id)})}
