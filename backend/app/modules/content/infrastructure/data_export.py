"""Content-module rows for the learner data export: the learner's Library, and labels for
Concepts referenced elsewhere in the export (shared content, not learner-owned)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.platform.persistence import select_rows


class LibraryDataSection:
    name = "library"

    def __init__(self, client: Any):
        self.client = client

    def export(self, user_id: UUID) -> list[dict]:
        items = select_rows(self.client, "learner_videos", "id,video_id,created_at", filters={"user_id": str(user_id)})
        videos = {
            row["id"]: row for row in select_rows(
                self.client, "videos", "id,source,external_video_id,title,original_language_code", filters={},
                in_filter=("id", [item["video_id"] for item in items]))
        }
        positions = {
            row["library_item_id"]: row["position_ms"] for row in select_rows(
                self.client, "learner_video_workspaces", "library_item_id,position_ms",
                filters={"user_id": str(user_id)})
        }
        return [{"added_at": item["created_at"], "video": videos.get(item["video_id"]),
                 "watch_position_ms": positions.get(item["id"])} for item in items]


class ConceptLabels:
    def __init__(self, client: Any):
        self.client = client

    def labels(self, concept_ids: list[str]) -> dict[str, str]:
        labels: dict[str, str] = {}
        for start in range(0, len(concept_ids), 200):
            for row in select_rows(self.client, "concepts", "id,canonical_text", filters={},
                                   in_filter=("id", concept_ids[start:start + 200])):
                labels[row["id"]] = row["canonical_text"]
        return labels
