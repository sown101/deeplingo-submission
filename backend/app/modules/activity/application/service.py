"""Recording into the learning log, reading it back with bounds, and the learner's study requests.

Every flow records through `record`, which never raises: the learner's action has already succeeded and a
lost log row must not undo it. Reads are always for one learner and one language, with a row cap.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.activity.domain.models import (
    MAX_REASON_CHARS,
    REQUEST_CLOSED_BY,
    STUDY_REQUEST_DEDUPE_DAYS,
    STUDY_REQUEST_ITEMS,
    ActivityEntry,
    ActivityError,
    ActivityRecord,
    StudyRequest,
)

logger = logging.getLogger(__name__)

MAX_READ_ROWS = 200
MAX_REQUEST_ROWS = 100
MAX_SOURCE_ROWS = 1000


class ActivityLogStore(Protocol):
    def insert_once(self, entry: ActivityEntry) -> bool:
        """Stores the entry unless (user_id, client_event_id) is already stored; True when it was added."""
        ...

    def recent(self, *, user_id: UUID, language_code: str, since: datetime | None, kinds: list[str] | None,
               limit: int) -> list[ActivityRecord]:
        """Newest first."""
        ...

    def for_source(self, *, user_id: UUID, source_type: str, source_id: str, limit: int) -> list[ActivityRecord]:
        """The learner's own rows of one source (a study region), newest first."""
        ...


class StudyRequestStore(Protocol):
    def open_for_item(self, *, user_id: UUID, language_code: str, kind: str, item_type: str, item_id: str,
                      created_after: datetime) -> StudyRequest | None: ...

    def create(self, *, user_id: UUID, language_code: str, kind: str, item_type: str, item_id: str,
               reason: str | None, created_by: str) -> StudyRequest: ...

    def list(self, *, user_id: UUID, language_code: str, status: str | None, limit: int) -> list[StudyRequest]: ...

    def close_open_for_item(self, *, user_id: UUID, language_code: str, item_type: str, item_id: str,
                            closed_at: datetime, kind: str | None = None) -> int:
        """Open -> done for the learner's open requests of this item (only of `kind` when given)."""
        ...

    def dismiss(self, *, user_id: UUID, request_id: UUID, closed_at: datetime) -> StudyRequest | None:
        """Open -> dismissed for the learner's own request; returns the row as it now is, or None if not theirs."""
        ...


class ActivityService:
    def __init__(self, *, log: ActivityLogStore, requests: StudyRequestStore,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.log, self.requests, self.clock = log, requests, clock

    def record(self, entry: ActivityEntry) -> bool:
        """True when a new row was stored. A retry with the same client_event_id stores nothing."""
        try:
            created = self.log.insert_once(entry)
        except Exception as exc:
            logger.warning("activity log write failed kind=%s error=%s", entry.kind, type(exc).__name__)
            return False
        closes = REQUEST_CLOSED_BY.get(entry.kind)
        if created and entry.outcome == "correct" and entry.item_type is not None and closes is not None:
            try:
                self.requests.close_open_for_item(user_id=entry.user_id, language_code=entry.language_code,
                                                  item_type=entry.item_type, item_id=entry.item_id,
                                                  closed_at=self.clock(), kind=closes)
            except Exception as exc:
                logger.warning("study requests not closed kind=%s error=%s", entry.kind, type(exc).__name__)
        return created

    def recent(self, user_id: UUID, *, language_code: str, since: datetime | None = None,
               kinds: list[str] | None = None, limit: int = 50) -> list[ActivityRecord]:
        return self.log.recent(user_id=user_id, language_code=language_code, since=since,
                               kinds=sorted(set(kinds)) if kinds else None, limit=max(1, min(limit, MAX_READ_ROWS)))

    def for_source(self, user_id: UUID, *, source_type: str, source_id: str,
                   limit: int = MAX_SOURCE_ROWS) -> list[ActivityRecord]:
        return self.log.for_source(user_id=user_id, source_type=source_type, source_id=source_id,
                                   limit=max(1, min(limit, MAX_SOURCE_ROWS)))

    def study_requests(self, user_id: UUID, *, language_code: str, status: str | None = None,
                       limit: int = MAX_REQUEST_ROWS) -> list[StudyRequest]:
        return self.requests.list(user_id=user_id, language_code=language_code, status=status,
                                  limit=max(1, min(limit, MAX_REQUEST_ROWS)))

    def create_study_request(self, user_id: UUID, *, language_code: str, kind: str, item_id: str,
                             reason: str | None, created_by: str) -> tuple[StudyRequest, bool]:
        """The caller has checked that the item exists in this language. The same open request from the last
        seven days is returned instead of a second one: (request, created)."""
        item_type = STUDY_REQUEST_ITEMS.get(kind)
        if item_type is None or created_by not in ("agent", "system"):
            raise ActivityError("Unknown study request.", status_code=422, code="study_request_invalid")
        reason = " ".join((reason or "").split())[:MAX_REASON_CHARS] or None
        existing = self.requests.open_for_item(
            user_id=user_id, language_code=language_code, kind=kind, item_type=item_type, item_id=item_id,
            created_after=self.clock() - timedelta(days=STUDY_REQUEST_DEDUPE_DAYS))
        if existing is not None:
            return existing, False
        return self.requests.create(user_id=user_id, language_code=language_code, kind=kind, item_type=item_type,
                                    item_id=item_id, reason=reason, created_by=created_by), True

    def dismiss(self, user_id: UUID, request_id: UUID) -> StudyRequest:
        """Open requests become dismissed; one already closed is returned as it is."""
        found = self.requests.dismiss(user_id=user_id, request_id=request_id, closed_at=self.clock())
        if found is None:
            raise ActivityError("Study request not found.", status_code=404, code="study_request_not_found")
        return found
