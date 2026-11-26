"""Redis storage for the agent: text conversations between turns, and the voice limits.

Conversations hold learner text, so they go only to the transient Redis (`COMPANION_SESSION_TEXT_REDIS_URL`: no
AOF, no snapshots, no replica; checked before every write). Keys: `deeplingo:agent:conversation:<learner>:<id>`,
with a time-to-live that ends with the conversation, and `...:used:<token id>` for each spent ticket.

The voice limits are counts only and go to the shared Redis (`REDIS_URL`): `deeplingo:realtime:slots` (a sorted set
of running sessions, scored by when each slot frees itself) and `deeplingo:realtime:seconds:<learner>:<day>`
(an integer, kept two days). Every change is one atomic command or one MULTI/EXEC transaction.

Values are never logged; a failure is raised as the port's typed error with the error's type only.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from uuid import UUID

from redis.exceptions import RedisError

from app.modules.learning.application.agent.ports import SessionStoreUnavailable
from app.modules.learning.application.agent.voice_limits import GateStoreUnavailable
from app.modules.learning.infrastructure.session_events import require_transient_redis

logger = logging.getLogger(__name__)

SECONDS_KEY_TTL = 2 * 86_400


class RedisSessionStore:
    def __init__(self, client, *, prefix: str = "deeplingo:agent:conversation"):
        self.client = client
        self.prefix = prefix

    def _key(self, conversation_id: UUID, user_id: UUID) -> str:
        return f"{self.prefix}:{user_id}:{conversation_id}"

    def get(self, conversation_id: UUID, user_id: UUID) -> dict | None:
        raw = self._call("get", lambda: self.client.get(self._key(conversation_id, user_id)))
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError as exc:
            logger.warning("agent conversation store returned an unreadable value")
            raise SessionStoreUnavailable("unreadable") from exc
        return value if isinstance(value, dict) else None

    def put(self, conversation_id: UUID, user_id: UUID, state: dict, *, ttl_seconds: int) -> None:
        value = json.dumps(state, ensure_ascii=False, separators=(",", ":"))

        def write():
            require_transient_redis(self.client)
            self.client.set(self._key(conversation_id, user_id), value, ex=max(1, ttl_seconds))
        self._call("put", write)

    def delete(self, conversation_id: UUID, user_id: UUID) -> None:
        self._call("delete", lambda: self.client.delete(self._key(conversation_id, user_id)))

    def claim(self, conversation_id: UUID, user_id: UUID, token_id: str, *, ttl_seconds: int) -> bool:
        key = f"{self._key(conversation_id, user_id)}:used:{token_id}"
        return bool(self._call("claim", lambda: self.client.set(key, "1", ex=max(1, ttl_seconds), nx=True)))

    def release(self, conversation_id: UUID, user_id: UUID, token_id: str) -> None:
        key = f"{self._key(conversation_id, user_id)}:used:{token_id}"
        self._call("release", lambda: self.client.delete(key))

    @staticmethod
    def _call(operation: str, action):
        try:
            return action()
        except (RedisError, OSError, RuntimeError) as exc:  # RuntimeError: the Redis is not transient
            logger.warning("agent conversation store failed operation=%s error=%s", operation, type(exc).__name__)
            raise SessionStoreUnavailable(operation) from exc


class RedisGateStore:
    def __init__(self, client, *, prefix: str = "deeplingo:realtime"):
        self.client = client
        self.slots = f"{prefix}:slots"
        self.prefix = prefix

    def open_session(self, handle: str, *, max_concurrent: int, until: float, now: float) -> bool:
        def run():
            pipe = self.client.pipeline(transaction=True)
            pipe.zremrangebyscore(self.slots, "-inf", now)  # slots of sessions that never ended free themselves
            pipe.zadd(self.slots, {handle: until})
            pipe.zcard(self.slots)
            pipe.expire(self.slots, SECONDS_KEY_TTL)
            held = pipe.execute()[2]
            if held > max_concurrent:
                self.client.zrem(self.slots, handle)
                return False
            return True
        return self._call("open_session", run)

    def close_session(self, handle: str) -> None:
        self._call("close_session", lambda: self.client.zrem(self.slots, handle))

    def add_seconds(self, user_id: UUID, day: date, amount: int) -> int:
        key = f"{self.prefix}:seconds:{user_id}:{day.isoformat()}"

        def run():
            pipe = self.client.pipeline(transaction=True)
            pipe.incrby(key, amount)
            pipe.expire(key, SECONDS_KEY_TTL)
            return int(pipe.execute()[0])
        return self._call("add_seconds", run)

    @staticmethod
    def _call(operation: str, action):
        try:
            return action()
        except (RedisError, OSError) as exc:
            logger.warning("realtime limit store failed operation=%s error=%s", operation, type(exc).__name__)
            raise GateStoreUnavailable(operation) from exc
