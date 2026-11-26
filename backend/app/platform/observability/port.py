"""Vendor-neutral tracing scoped to one text agent turn."""
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class Observation:
    capture_content: bool
    status: Literal["ok", "error", "refused", "declined"] = "ok"
    failure_category: str | None = None
    usage: dict[str, int] | None = None
    estimated_cost_usd: float | None = None
    input: str | list[str] | None = field(default=None, repr=False)
    output: str | None = field(default=None, repr=False)


class Turn(Protocol):
    tool_rounds: int

    def span(self, kind: Literal["generation", "tool"], name: str, *,
             model: str | None = None) -> AbstractContextManager[Observation | None]: ...


class TurnTracing(Protocol):
    def turn(self, phase: Literal["start", "turn"]) -> AbstractContextManager[Turn | None]: ...


class NoopTracing:
    def turn(self, phase: Literal["start", "turn"]) -> AbstractContextManager[Turn | None]:
        return nullcontext()


_TURN: ContextVar[Turn | None] = ContextVar("text_agent_turn_trace", default=None)


@contextmanager
def trace_turn(tracing: TurnTracing, phase: Literal["start", "turn"]) -> Iterator[None]:
    with tracing.turn(phase) as turn:
        token = _TURN.set(turn)
        try:
            yield
        finally:
            _TURN.reset(token)


def current_turn() -> Turn | None:
    return _TURN.get()
