"""Target statuses and compatibility settings for the learner API.

Legacy backlog rows are treated as active; new saves need no activation gate.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DAILY_NEW_LIMIT = 10
MIN_DAILY_NEW_LIMIT = 1
MAX_DAILY_NEW_LIMIT = 50

PRIORITY_EXPLICIT = 100  # the learner saved it
PRIORITY_LOOKUP = 50  # looked up, queued by the system
PRIORITY_IMPORT = 40  # imported in a list
PRIORITY_CONTENT = 10  # offered from a video
MAX_PRIORITY = 1000


class TargetStatus(str, Enum):
    BACKLOG = "backlog"
    ACTIVE = "active"
    SUSPENDED = "suspended"


def validate_daily_new_limit(value: int) -> int:
    if not MIN_DAILY_NEW_LIMIT <= value <= MAX_DAILY_NEW_LIMIT:
        raise ValueError(f"daily_new_limit must be between {MIN_DAILY_NEW_LIMIT} and {MAX_DAILY_NEW_LIMIT}")
    return value


def resolve_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_day_start(now: datetime, timezone_name: str | None) -> datetime:
    """Midnight of the learner's current local day, as an aware UTC instant."""
    tz = resolve_timezone(timezone_name)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
