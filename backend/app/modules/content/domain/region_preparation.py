"""M1 S2 region preparation values: learning preparation of one study region.

A region preparation is global content readiness for one segment range of one transcript
version, per support language and preparation version. It is not learner state; the learner
only asks for it (and is charged once per new region against a bounded budget).
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RegionPreparationStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    NO_CONTENT = "no_content"
    FAILED = "failed"


# Outcomes of an admission that do not correspond to a stored region row.
# M1 S7b: `busy` = Content work is at its shared safety cap; asking again later is not charged.
ADMISSION_ONLY_STATUSES = frozenset({
    "not_found", "region_unavailable", "transcript_unavailable", "budget_exhausted", "busy",
})


class RegionPreparation(BaseModel):
    id: UUID
    video_id: UUID
    transcript_id: UUID
    start_segment_id: UUID
    end_segment_id: UUID
    start_sequence: int
    end_sequence: int
    support_language_code: str
    preparation_version: str
    status: RegionPreparationStatus
    usable_count: int = 0
    failure_code: str | None = None
    retryable: bool = False
    questions_status: str | None = None  # M1 S6
    updated_at: datetime | None = None

    def covers(self, sequence_number: int) -> bool:
        return self.start_sequence <= sequence_number <= self.end_sequence


@dataclass(frozen=True)
class RegionAdmission:
    """What `admit_region_preparation` decided for one request."""

    status: str
    region_preparation_id: UUID | None = None
    intent_id: UUID | None = None
    dispatch_now: bool = False
    usable_count: int = 0
    retryable: bool = False
    reset_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "RegionAdmission":
        status = str(row["status"])
        if status not in ADMISSION_ONLY_STATUSES and status not in {item.value for item in RegionPreparationStatus}:
            raise ValueError("Unknown region admission status")
        reset_at = row.get("reset_at")
        return cls(
            status=status,
            region_preparation_id=UUID(str(row["region_preparation_id"])) if row.get("region_preparation_id") else None,
            intent_id=UUID(str(row["intent_id"])) if row.get("intent_id") else None,
            dispatch_now=bool(row.get("dispatch_now")),
            usable_count=int(row.get("usable_count") or 0),
            retryable=bool(row.get("retryable")),
            reset_at=datetime.fromisoformat(str(reset_at).replace("Z", "+00:00")) if reset_at else None,
        )


# M1 S7b: failure code of a ready region where some sentences failed (usable, but not complete).
PARTIAL_PREPARATION = "partial_preparation"


def covered_sequences(regions: list[RegionPreparation], *, exclude: UUID | None = None) -> set[int]:
    """Segment sequence numbers fully prepared by finished regions (ready or no content, with no
    failed sentence)."""
    done = {RegionPreparationStatus.READY, RegionPreparationStatus.NO_CONTENT}
    covered: set[int] = set()
    for region in regions:
        if region.id != exclude and region.status in done and region.failure_code is None:
            covered.update(range(region.start_sequence, region.end_sequence + 1))
    return covered
