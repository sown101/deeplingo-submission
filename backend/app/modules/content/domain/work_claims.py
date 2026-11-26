"""Vendor-neutral, server-owned Content execution identity."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

CONTENT_STAGES = frozenset({"transcript", "learning_preparation", "region_preparation"})


class StaleContentClaim(RuntimeError):
    """Ownership was lost; neither success nor failure may mutate content."""


@dataclass(frozen=True)
class ContentClaim:
    intent_id: UUID
    video_id: UUID
    stage: str
    generation: int
    token: UUID
    epoch: int
    lease_expires_at: datetime
    # M1 S2: set exactly when stage is region_preparation (the claimed region row).
    region_preparation_id: UUID | None = None

    def __post_init__(self):
        if self.epoch < 1 or self.generation < 1:
            raise ValueError("Content claim requires positive epoch/generation")
        if self.stage not in CONTENT_STAGES:
            raise ValueError("Unsupported Content execution stage")
        if (self.stage == "region_preparation") != (self.region_preparation_id is not None):
            raise ValueError("Region preparation claim requires exactly its region")
        if self.lease_expires_at.tzinfo is None:
            raise ValueError("Content lease requires a timezone")
