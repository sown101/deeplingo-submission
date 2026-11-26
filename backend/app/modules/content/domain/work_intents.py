"""Durable Content work intent values (one per active V3 stage)."""
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.content.domain.catalog import Video
from app.modules.content.domain.library import LearnerVideo


@dataclass(frozen=True)
class AdmittedVideoWork:
    association: LearnerVideo
    video: Video
    intent_id: UUID | None
    command_status: str
    dispatch_now: bool


@dataclass(frozen=True)
class VideoWorkIntent:
    id: UUID
    video_id: UUID
    stage: str
    generation: int
    state: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "VideoWorkIntent":
        return cls(
            id=UUID(str(row["id"])),
            video_id=UUID(str(row["video_id"])),
            stage=str(row["stage"]),
            generation=int(row["generation"]),
            state=str(row["state"]),
        )
