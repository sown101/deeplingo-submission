"""Progress of one learner: asks the store for their totals (summed in the database) and shapes the view."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.modules.progress.domain.models import (
    ProgressTotals,
    ProgressView,
    as_utc,
    build_progress,
)

MAX_UTC_OFFSET_MINUTES = 14 * 60


class ProgressError(ValueError):
    pass


class ProgressStore(Protocol):
    def totals(self, *, user_id: UUID, language_code: str | None, now: datetime,
               utc_offset_minutes: int) -> ProgressTotals:
        """The learner's own log, cards and scores, summed for the window that ends today at that offset."""
        ...

    def languages(self, *, user_id: UUID) -> list[str]:
        """The languages the learner studies."""
        ...


class ProgressService:
    def __init__(self, *, store: ProgressStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.store, self.clock = store, clock

    def progress(self, user_id: UUID, *, language: str | None, utc_offset_minutes: int = 0) -> ProgressView:
        if abs(utc_offset_minutes) > MAX_UTC_OFFSET_MINUTES:
            raise ProgressError("utc_offset_out_of_range")
        now = as_utc(self.clock())
        languages = self.store.languages(user_id=user_id)
        totals = self.store.totals(user_id=user_id, language_code=language, now=now,
                                   utc_offset_minutes=utc_offset_minutes)
        # A language the learner has data in but no preference row for still appears in the filter.
        return build_progress(totals, languages + [code for code in totals.data_languages if code not in languages],
                              language=language, now=now, utc_offset_minutes=utc_offset_minutes)
