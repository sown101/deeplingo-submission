"""Sliding-window limits for provider-backed learner actions.

They bound accidental client loops and abuse. The counts live in a `WindowStore`: this process's memory by default,
or Redis (`RedisWindowStore`, used when `REDIS_URL` is set) so that every API process shares them and a restart
keeps them. If Redis cannot be reached the limiter fails open to this process's own counts: requests are still
limited, per process, rather than all refused (the voice budget, which costs money per second, fails closed in
`RealtimeGate` instead).
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Callable, Protocol
from uuid import uuid4

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RateLimitStoreUnavailable(Exception):
    pass


class WindowStore(Protocol):
    def hit(self, key: str, *, limit: int, window: float, now: float) -> bool:
        """Count one event at `now` unless `limit` events are already in the last `window` seconds (atomic)."""
        ...


class MemoryWindowStore:
    def __init__(self):
        self._events: dict[str, tuple[deque[float], float]] = {}
        self._sweep_at = -math.inf
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window: float, now: float) -> bool:
        with self._lock:
            if now >= self._sweep_at:
                self._events = {name: entry for name, entry in self._events.items() if entry[1] > now}
                self._sweep_at = now + 60
            events, _ = self._events.get(key, (deque(), now))
            while events and now - events[0] >= window:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            self._events[key] = events, now + window
            return True


class RedisWindowStore:
    """One sorted set per action and subject (`deeplingo:ratelimit:<action>:<subject>`), scored by time. The event
    is added, old ones dropped and the set counted in one MULTI/EXEC; a refused event is taken out again."""

    def __init__(self, client, *, prefix: str = "deeplingo:ratelimit"):
        self.client = client
        self.prefix = prefix

    def hit(self, key: str, *, limit: int, window: float, now: float) -> bool:
        name, member = f"{self.prefix}:{key}", f"{now:.6f}:{uuid4().hex[:12]}"
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.zremrangebyscore(name, "-inf", now - window)
            pipe.zadd(name, {member: now})
            pipe.zcard(name)
            pipe.expire(name, math.ceil(window) + 1)
            count = pipe.execute()[2]
            if count > limit:
                self.client.zrem(name, member)
                return False
            return True
        except (RedisError, OSError) as exc:
            raise RateLimitStoreUnavailable(type(exc).__name__) from exc


class SlidingWindowLimiter:
    def __init__(self, limits: dict[str, tuple[int, float]], clock: Callable[[], float] = time.monotonic,
                 store: WindowStore | None = None):
        self._limits = limits
        self._clock = clock  # a shared store needs a wall clock (time.time), the same in every process
        self._local = MemoryWindowStore()
        self._store = store if store is not None else self._local

    def allow(self, subject: str, action: str) -> bool:
        limit, window = self._limits[action]
        key, now = f"{action}:{subject}", self._clock()
        try:
            return self._store.hit(key, limit=limit, window=window, now=now)
        except RateLimitStoreUnavailable as exc:
            logger.warning("rate limit store unavailable; counting in this process action=%s error=%s", action, exc)
            return self._local.hit(key, limit=limit, window=window, now=now)
