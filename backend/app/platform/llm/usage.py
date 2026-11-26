"""M1 S7: which piece of work an LLM call is spent on, for cost per region and per session.

A scope is `kind:id` (for example `region_preparation:<region id>` or `companion:<Library item id>`).
It names content or a Library item, never a learner, prompt or reply. Calls outside a scope log
`scope=none`.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from uuid import UUID

_SCOPE: ContextVar[str | None] = ContextVar("llm_usage_scope", default=None)


@contextmanager
def usage_scope(kind: str, scope_id: UUID | str | None) -> Iterator[None]:
    token = _SCOPE.set(f"{kind}:{scope_id if scope_id is not None else 'none'}")
    try:
        yield
    finally:
        _SCOPE.reset(token)


def current_usage_scope() -> str:
    return _SCOPE.get() or "none"
