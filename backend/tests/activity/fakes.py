"""One in-memory learning log and study-request store shared by the activity tests."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.modules.activity.application.service import ActivityService
from app.modules.activity.domain.models import ActivityEntry, ActivityRecord, StudyRequest

START = datetime(2026, 11, 14, 8, 0, tzinfo=UTC)


class MemoryLog:
    def __init__(self):
        self.entries: list[ActivityEntry] = []
        self.times: list[datetime] = []

    def insert_once(self, entry: ActivityEntry) -> bool:
        if any((row.user_id, row.client_event_id) == (entry.user_id, entry.client_event_id) for row in self.entries):
            return False
        self.entries.append(entry)
        self.times.append(entry.occurred_at or START + timedelta(minutes=len(self.entries)))
        return True

    def recent(self, *, user_id, language_code, since, kinds, limit):
        rows = [(when, entry) for when, entry in zip(self.times, self.entries)
                if entry.user_id == user_id and entry.language_code == language_code
                and (since is None or when >= since) and (not kinds or entry.kind in kinds)]
        rows.sort(key=lambda pair: pair[0], reverse=True)
        return [ActivityRecord(id=uuid4(), occurred_at=when, **entry.model_dump(
            include={"language_code", "kind", "item_type", "item_id", "source_type", "source_id", "outcome", "score",
                     "detail"})) for when, entry in rows[:limit]]

    def for_source(self, *, user_id, source_type, source_id, limit):
        rows = [(when, entry) for when, entry in zip(self.times, self.entries)
                if (entry.user_id, entry.source_type, entry.source_id) == (user_id, source_type, source_id)]
        rows.sort(key=lambda pair: pair[0], reverse=True)
        return [ActivityRecord(id=uuid4(), occurred_at=when, **entry.model_dump(
            include={"language_code", "kind", "item_type", "item_id", "source_type", "source_id", "outcome", "score",
                     "detail"})) for when, entry in rows[:limit]]

    def of(self, kind: str | None = None) -> list[ActivityEntry]:
        return [entry for entry in self.entries if kind is None or entry.kind == kind]


class MemoryRequests:
    def __init__(self, clock):
        self.rows: list[StudyRequest] = []
        self.clock = clock

    def open_for_item(self, *, user_id, language_code, kind, item_type, item_id, created_after):
        return next((row for row in self.rows if (row.user_id, row.language_code, row.kind, row.item_type,
                                                  row.item_id, row.status) == (user_id, language_code, kind, item_type,
                                                                              item_id, "open")
                     and row.created_at >= created_after), None)

    def create(self, *, user_id, language_code, kind, item_type, item_id, reason, created_by):
        row = StudyRequest(id=uuid4(), user_id=user_id, language_code=language_code, kind=kind, item_type=item_type,
                           item_id=item_id, reason=reason, status="open", created_by=created_by,
                           created_at=self.clock())
        self.rows.append(row)
        return row

    def list(self, *, user_id, language_code, status, limit):
        rows = [row for row in self.rows if row.user_id == user_id and row.language_code == language_code
                and (status is None or row.status == status)]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)[:limit]

    def close_open_for_item(self, *, user_id, language_code, item_type, item_id, closed_at, kind=None):
        closed = 0
        for index, row in enumerate(self.rows):
            if (row.user_id, row.language_code, row.item_type, row.item_id, row.status) == (
                    user_id, language_code, item_type, item_id, "open") and kind in (None, row.kind):
                self.rows[index] = row.model_copy(update={"status": "done", "closed_at": closed_at})
                closed += 1
        return closed

    def dismiss(self, *, user_id, request_id: UUID, closed_at):
        for index, row in enumerate(self.rows):
            if row.id == request_id and row.user_id == user_id:
                if row.status == "open":
                    self.rows[index] = row = row.model_copy(update={"status": "dismissed", "closed_at": closed_at})
                return row
        return None


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


def make_activity(log=None):
    """(service, log, requests, clock): the real ActivityService over in-memory stores."""
    log, clock = log or MemoryLog(), Clock()
    requests = MemoryRequests(clock)
    return ActivityService(log=log, requests=requests, clock=clock), log, requests, clock


class BrokenLog:
    """A log store that is down: recording must never fail the learner's action."""

    def insert_once(self, entry):
        raise ConnectionError("database down")
