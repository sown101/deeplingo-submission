"""The voice channel's ports: the realtime provider (Gemini Live) and the learner's WebSocket, as the relay sees them."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AudioOut:
    pcm: bytes
    sample_rate: int


@dataclass(frozen=True)
class TranscriptPiece:
    role: Literal["learner", "companion"]
    text: str


@dataclass(frozen=True)
class TurnComplete:
    pass


@dataclass(frozen=True)
class Interrupted:
    pass


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ResumptionUpdate:
    """The provider's latest handle for resuming this session on a new connection (None: not resumable now)."""
    handle: str | None
    resumable: bool


@dataclass(frozen=True)
class GoAway:
    """The provider will close this connection soon (its connection lifetime); resume on a new one."""
    time_left_ms: int | None = None


@dataclass(frozen=True)
class Resumed:
    """The session continues on a new provider connection (made by ResumableConnection)."""


RealtimeEvent = AudioOut | TranscriptPiece | TurnComplete | Interrupted | ToolCall | ResumptionUpdate | GoAway | Resumed


class RealtimeUnavailable(Exception):
    """The provider session could not be opened or broke; never learner failure."""


class RealtimeConnection(Protocol):
    async def send_audio(self, pcm: bytes) -> None: ...

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None: ...

    async def send_text(self, text: str) -> None:
        """A server-written cue for the model (never learner text)."""
        ...

    async def send_context(self, text: str) -> None:
        """A server-written note the model keeps in mind; unlike a cue it does not start a reply."""
        ...

    def events(self) -> AsyncIterator[RealtimeEvent]: ...

    async def close(self) -> None: ...


class RealtimeVoice(Protocol):
    model_name: str

    async def open(self, *, language_code: str, instruction: str, silence_ms: int,
                   resume_handle: str | None = None) -> RealtimeConnection:
        """A new provider session, or with `resume_handle` the same session continued on a new connection."""
        ...


class ClientChannel(Protocol):
    """The learner's WebSocket, as seen by the relay."""

    async def receive(self) -> tuple[str, bytes | str | None]:
        """("bytes", data) | ("text", data) | ("closed", None)."""
        ...

    async def send_json(self, message: dict) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...

    async def close(self, code: int) -> None: ...


class TokenVerifier(Protocol):
    def verify(self, token: str): ...

