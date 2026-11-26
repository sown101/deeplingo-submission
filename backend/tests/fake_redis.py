"""An in-test stand-in for Redis: exactly the commands the app's Redis stores use, nothing else.

Commands run one at a time under a lock, and a MULTI/EXEC pipeline runs as one step, as on a Redis server. Keys
expire on a clock the test controls. `down = True` makes every command fail as an unreachable server does;
`persistent = True` reports AOF on (a Redis that writes to disk). No real Redis is ever contacted.
"""
from __future__ import annotations

import threading

from redis.exceptions import ConnectionError as RedisConnectionError


class FakeRedis:
    def __init__(self, *, clock=lambda: 0.0, persistent: bool = False):
        self.clock = clock
        self.persistent = persistent
        self.down = False
        self.data: dict[str, object] = {}  # str, int, or dict (sorted set: member -> score)
        self.expiry: dict[str, float] = {}
        self.commands: list[str] = []
        self._lock = threading.RLock()

    # --- plumbing ---------------------------------------------------------------------------

    def _check(self, name: str) -> None:
        if self.down:
            raise RedisConnectionError("Error connecting to fake redis")
        self.commands.append(name)

    def _live(self, key: str):
        if key in self.expiry and self.expiry[key] <= self.clock():
            self.data.pop(key, None)
            self.expiry.pop(key, None)
        return self.data.get(key)

    def ttl_of(self, key: str) -> float | None:
        return self.expiry[key] - self.clock() if key in self.expiry else None

    # --- strings ----------------------------------------------------------------------------

    def get(self, key):
        with self._lock:
            self._check("GET")
            value = self._live(key)
            return None if value is None else str(value)

    def set(self, key, value, ex=None, nx=False):
        with self._lock:
            self._check("SET")
            if nx and self._live(key) is not None:
                return None
            self.data[key] = value
            self.expiry.pop(key, None)
            if ex is not None:
                self.expiry[key] = self.clock() + ex
            return True

    def delete(self, *keys):
        with self._lock:
            self._check("DEL")
            removed = 0
            for key in keys:
                if self._live(key) is not None:
                    removed += 1
                self.data.pop(key, None)
                self.expiry.pop(key, None)
            return removed

    def incrby(self, key, amount):
        with self._lock:
            self._check("INCRBY")
            value = int(self._live(key) or 0) + int(amount)
            self.data[key] = value
            return value

    def expire(self, key, seconds):
        with self._lock:
            self._check("EXPIRE")
            if self._live(key) is None:
                return False
            self.expiry[key] = self.clock() + seconds
            return True

    # --- sorted sets ------------------------------------------------------------------------

    def _zset(self, key) -> dict:
        value = self._live(key)
        if value is None:
            value = {}
            self.data[key] = value
        return value

    def zadd(self, key, mapping):
        with self._lock:
            self._check("ZADD")
            zset = self._zset(key)
            added = sum(1 for member in mapping if member not in zset)
            zset.update({member: float(score) for member, score in mapping.items()})
            return added

    def zrem(self, key, *members):
        with self._lock:
            self._check("ZREM")
            zset = self._live(key) or {}
            return sum(1 for member in members if zset.pop(member, None) is not None)

    def zcard(self, key):
        with self._lock:
            self._check("ZCARD")
            return len(self._live(key) or {})

    def zremrangebyscore(self, key, low, high):
        with self._lock:
            self._check("ZREMRANGEBYSCORE")
            zset = self._live(key) or {}
            low = float("-inf") if low == "-inf" else float(low)
            gone = [member for member, score in zset.items() if low <= score <= float(high)]
            for member in gone:
                del zset[member]
            return len(gone)

    # --- server -----------------------------------------------------------------------------

    def config_get(self, *names):
        with self._lock:
            self._check("CONFIG GET")
            return {"appendonly": "yes" if self.persistent else "no", "save": "3600 1" if self.persistent else ""}

    def info(self, section):
        with self._lock:
            self._check("INFO")
            return {"role": "master", "connected_slaves": 0}

    def pipeline(self, transaction=True):
        assert transaction, "the app only uses MULTI/EXEC pipelines"
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: FakeRedis):
        self.redis, self.queued = redis, []

    def __getattr__(self, name):
        if name not in ("zremrangebyscore", "zadd", "zcard", "expire", "incrby"):
            raise AttributeError(name)

        def queue(*args, **kwargs):
            self.queued.append((name, args, kwargs))
            return self
        return queue

    def execute(self):
        with self.redis._lock:  # MULTI ... EXEC: nothing else runs in between
            self.redis._check("EXEC")
            return [getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.queued]
