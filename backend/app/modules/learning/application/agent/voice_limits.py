"""The voice channel's limits: concurrent sessions and seconds per learner per UTC day (fail closed)."""
from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.modules.learning.domain.realtime import RealtimeLimits

logger = logging.getLogger(__name__)

SESSION_SLOT_SLACK_S = 120  # a running session's slot outlives its grant by this much, then frees itself


class GateStoreUnavailable(Exception):
    """The store of the voice limits could not be reached."""


class RealtimeGateUnavailable(Exception):
    """The voice limits cannot be checked: no session is granted (fail closed)."""


class GateStore(Protocol):
    """Shared counts of the voice limits. Each call is atomic; failures raise GateStoreUnavailable."""

    def open_session(self, handle: str, *, max_concurrent: int, until: float, now: float) -> bool:
        """Hold one of `max_concurrent` session slots until `until` (or close); False when all are held."""
        ...

    def close_session(self, handle: str) -> None: ...

    def add_seconds(self, user_id: UUID, day: date, amount: int) -> int:
        """Add (or, negative, give back) seconds to the learner's count for the UTC day; returns the new count."""
        ...


class MemoryGateStore:
    """The counts of one API process: a restart forgets them and a second process counts separately."""

    def __init__(self):
        self._slots: dict[str, float] = {}
        self._seconds: dict[tuple[UUID, date], int] = {}
        self._lock = threading.Lock()

    def open_session(self, handle: str, *, max_concurrent: int, until: float, now: float) -> bool:
        with self._lock:
            self._slots = {key: end for key, end in self._slots.items() if end > now}
            if len(self._slots) >= max_concurrent:
                return False
            self._slots[handle] = until
            return True

    def close_session(self, handle: str) -> None:
        with self._lock:
            self._slots.pop(handle, None)

    def add_seconds(self, user_id: UUID, day: date, amount: int) -> int:
        with self._lock:
            key = (user_id, day)
            self._seconds[key] = self._seconds.get(key, 0) + amount
            return self._seconds[key]


class SessionGrant(int):
    """The seconds a session may last; it also remembers which slot it holds, so releasing frees that slot."""

    handle: str | None = None


class RealtimeGate:
    """Concurrent sessions and seconds per learner per UTC day, counted in a `GateStore` (one process's memory by
    default; Redis when configured, so a restart keeps the day's seconds and every API process shares them).

    A new session reserves the longest grant first and gives back what it may not use, so sessions opened together
    can never spend more than the day's allowance; when the session ends, the seconds it really used replace its
    grant (rounded up to whole seconds). The store failing means no session (fail closed: RealtimeGateUnavailable).
    """

    def __init__(self, limits: RealtimeLimits, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 store: GateStore | None = None):
        self.limits = limits
        self.clock = clock
        self.store = store if store is not None else MemoryGateStore()
        self._held: dict[UUID, list[tuple[str, date, int]]] = {}  # this process's running sessions: slot, day, grant
        self._lock = threading.Lock()

    def acquire(self, user_id: UUID) -> SessionGrant | None:
        """Seconds this session may last (pass the result to `release`), or None when a limit is reached."""
        limits, now = self.limits, self.clock()
        day, handle, longest = now.date(), f"{user_id}:{uuid4().hex}", limits.max_session_seconds
        try:
            if not self.store.open_session(handle, max_concurrent=limits.max_concurrent_sessions,
                                           until=now.timestamp() + longest + SESSION_SLOT_SLACK_S,
                                           now=now.timestamp()):
                return None
            try:
                left = limits.daily_seconds_per_learner - (self.store.add_seconds(user_id, day, longest) - longest)
                granted = int(min(longest, left))
                if left < 30:
                    self.store.add_seconds(user_id, day, -longest)
                    self.store.close_session(handle)
                    return None
                if granted < longest:
                    self.store.add_seconds(user_id, day, granted - longest)
            except GateStoreUnavailable:
                self._close_quietly(handle)
                raise
        except GateStoreUnavailable as exc:
            logger.warning("realtime limits unavailable; session refused")
            raise RealtimeGateUnavailable() from exc
        with self._lock:
            self._held.setdefault(user_id, []).append((handle, day, granted))
        grant = SessionGrant(granted)
        grant.handle = handle
        return grant

    def release(self, user_id: UUID, seconds: float, grant: int | None = None) -> None:
        """Free this session's slot. Without the grant (or with one this process does not hold) the oldest slot of
        the learner is freed."""
        used = math.ceil(max(0.0, seconds))
        wanted = getattr(grant, "handle", None)
        with self._lock:
            held = self._held.get(user_id)
            index = next((i for i, entry in enumerate(held or []) if wanted and entry[0] == wanted), 0)
            handle, day, granted = held.pop(index) if held else (None, self.clock().date(), 0)
        try:
            self.store.add_seconds(user_id, day, used - granted)
            if handle is not None:
                self.store.close_session(handle)
        except GateStoreUnavailable:
            # The grant stays counted for the day and the slot frees itself when it expires (fail closed).
            logger.warning("realtime limits not updated at the end of a session")

    def _close_quietly(self, handle: str) -> None:
        try:
            self.store.close_session(handle)
        except GateStoreUnavailable:
            pass

