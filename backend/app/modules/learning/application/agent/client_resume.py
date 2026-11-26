"""ReattachableChannel: the learner's side of a Live session survives a dropped WebSocket (harness plan, phase 3).

Every JSON event to the learner is numbered (1, 2, ... in sending order; the number is not in the message: the client
counts the events it received, which arrive in order) and the latest ones are kept. When the learner's socket
drops without the learner ending the conversation, the session goes on for REATTACH_GRACE_S: the client opens a new
socket, authenticates and sends {"type": "resume", "session_id": ..., "last_seq": n}; the events after n are sent
again and the conversation continues on the new socket. Audio meant for the learner while no socket is attached is
dropped (it cannot be heard later); events are kept. After the grace period the session ends as before
("learner_left"). Sessions are found in this process only: a client that reaches another API process starts again.
"""
from __future__ import annotations

import asyncio
from collections import deque
from uuid import UUID

from app.modules.learning.application.agent.realtime_port import ClientChannel

REATTACH_GRACE_S = 8.0
MAX_KEPT_EVENTS = 300
# This process's running voice sessions, by id. Module-wide: the API builds a VoiceChannel per WebSocket, so a
# registry on the channel object would never be seen by the learner's new socket.
RUNNING: dict[UUID, "ReattachableChannel"] = {}


class ReattachableChannel:
    def __init__(self, channel: ClientChannel, *, user_id: UUID, grace_s: float | None = None):
        self.current: ClientChannel | None = channel
        self.user_id = user_id
        self.grace_s = REATTACH_GRACE_S if grace_s is None else grace_s
        self.seq = 0
        self.kept: deque[tuple[int, dict]] = deque(maxlen=MAX_KEPT_EVENTS)
        self.reattaches = 0
        self._attached = asyncio.Event()
        self._attached.set()
        self.finished = asyncio.Event()  # the session is over; a reattached socket's handler may return

    # --- To the learner ----------------------------------------------------------------------

    async def send_json(self, message: dict) -> None:
        self.seq += 1
        self.kept.append((self.seq, message))
        channel = self.current
        if channel is None:
            return  # kept for the client's resume
        try:
            await channel.send_json(message)
        except Exception:
            self._detach(channel)

    async def send_bytes(self, data: bytes) -> None:
        channel = self.current
        if channel is None:
            return
        try:
            await channel.send_bytes(data)
        except Exception:
            self._detach(channel)

    async def close(self, code: int) -> None:
        self.finished.set()
        channel, self.current = self.current, None
        if channel is not None:
            await channel.close(code)

    # --- From the learner --------------------------------------------------------------------

    async def receive(self) -> tuple[str, bytes | str | None]:
        while True:
            channel = self.current
            if channel is None:
                if not await self._wait_for_socket():
                    return "closed", None
                continue
            kind, data = await channel.receive()
            if kind != "closed":
                return kind, data
            self._detach(channel)

    def _detach(self, channel: ClientChannel) -> None:
        if self.current is channel:
            self.current = None
            self._attached.clear()

    async def _wait_for_socket(self) -> bool:
        if self.finished.is_set():
            return False
        try:
            await asyncio.wait_for(self._attached.wait(), self.grace_s)
        except TimeoutError:
            return False
        return self.current is not None

    async def attach(self, channel: ClientChannel, last_seq: int) -> bool:
        """A new socket of the same learner takes over; the events after `last_seq` are sent again on it."""
        if self.finished.is_set():
            return False
        old, self.current = self.current, None
        self._attached.clear()
        if old is not None:
            # The client noticed the drop before the server did: the old socket goes, its reader moves on.
            try:
                await old.close(4000)
            except Exception:
                pass
        for seq, message in list(self.kept):
            if seq > last_seq:
                await channel.send_json(message)
        self.current = channel
        self.reattaches += 1
        self._attached.set()
        return True
