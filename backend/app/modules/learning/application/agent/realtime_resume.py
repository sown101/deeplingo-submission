"""ResumableConnection: a Live session that outlives one provider connection (agent harness plan, phase 3).

A provider connection has a limited lifetime: Gemini Live sends `goAway` shortly before it closes one, and a network
fault can drop it at any time. The provider also sends, as the conversation goes on, a handle that continues the
same session (its context, the conversation so far) on a new connection. This wrapper keeps the latest handle and,
when the connection is about to go or has gone, opens a new one with it and goes on reading, so the relay (and the
learner) sees one conversation. Without a handle, or after MAX_RESUMES, it behaves exactly like the connection it
wraps: the session ends as before ("provider_closed").

While the new connection opens, the learner's audio is dropped (a few hundred milliseconds); a tool response or
cue waits for the new connection, so the model is never left without one.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.modules.learning.application.agent.realtime_port import (
    GoAway,
    RealtimeConnection,
    RealtimeEvent,
    RealtimeUnavailable,
    RealtimeVoice,
    Resumed,
    ResumptionUpdate,
)

logger = logging.getLogger(__name__)

MAX_RESUMES = 6  # new connections one conversation may open (a connection lives about ten minutes)
REOPEN_WAIT_S = 20.0  # how long a send waits for a new connection before it gives up


class ResumableConnection:
    def __init__(self, voice: RealtimeVoice, connection: RealtimeConnection, *, open_args: dict,
                 max_resumes: int = MAX_RESUMES):
        self.voice, self.current, self.open_args = voice, connection, dict(open_args)
        self.handle: str | None = None
        self.resumes, self.max_resumes = 0, max_resumes
        self._ready = asyncio.Event()
        self._ready.set()
        self._closed = False

    # --- To the provider ---------------------------------------------------------------------

    async def send_audio(self, pcm: bytes) -> None:
        if not self._ready.is_set():
            return  # reconnecting: this audio is dropped
        try:
            await self.current.send_audio(pcm)
        except RealtimeUnavailable:
            if self.handle is None:
                raise
            # The reader resumes the session; audio sent meanwhile is lost.

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        await self._send(lambda connection: connection.send_tool_response(call_id, name, response))

    async def send_text(self, text: str) -> None:
        await self._send(lambda connection: connection.send_text(text))

    async def send_context(self, text: str) -> None:
        async def note(connection) -> None:
            send = getattr(connection, "send_context", None)
            if send is not None:  # a connection that cannot take a note without a reply goes without it
                await send(text)
        await self._send(note)

    async def _send(self, action) -> None:
        """A message the model needs: sent on the current connection, or on the next one when this one is going."""
        for _ in range(2):
            try:
                await asyncio.wait_for(self._ready.wait(), REOPEN_WAIT_S)
            except TimeoutError as exc:
                raise RealtimeUnavailable("provider not resumed") from exc
            connection = self.current
            try:
                await action(connection)
                return
            except RealtimeUnavailable:
                if self.handle is None:
                    raise
                if connection is self.current:
                    self._ready.clear()  # the reader will reconnect; wait for it once
        raise RealtimeUnavailable("provider closed")

    async def close(self) -> None:
        self._closed = True
        await self.current.close()

    # --- From the provider -------------------------------------------------------------------

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            try:
                async for event in self.current.events():
                    if isinstance(event, ResumptionUpdate):
                        self.handle = event.handle if event.resumable and event.handle else self.handle
                        continue
                    if isinstance(event, GoAway):
                        break  # resume now, before the provider closes this connection
                    yield event
            except RealtimeUnavailable:
                if self.handle is None or self._closed:
                    raise
            else:
                if self._closed:
                    return
                if self.handle is None:
                    return  # the provider ended the session and it cannot be continued
            if not await self._reopen():
                raise RealtimeUnavailable("provider session could not be resumed")
            yield Resumed()

    async def _reopen(self) -> bool:
        if self.handle is None or self.resumes >= self.max_resumes:
            return False
        self._ready.clear()
        old = self.current
        try:
            self.current = await self.voice.open(**self.open_args, resume_handle=self.handle)
        except Exception as exc:
            logger.warning("realtime session not resumed error=%s", type(exc).__name__)
            return False
        self.resumes += 1
        self._ready.set()
        try:
            await old.close()
        except Exception:
            pass
        return True
