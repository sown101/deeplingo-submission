"""AI cost ledger (owner decision 2026-11-05): token counts of every structured model call, kept so the
real cost per feature, model and day can be measured and optimized later.

A row holds the provider, model, response model, the usage scope's kind (`region_preparation`,
`lookup`, ...) and token counts. Never a prompt, an answer, a learner, a Library item or a scope id.
Writing is best effort on a background thread: a failed or slow write never delays or fails a call.
"""
from __future__ import annotations

import logging
import queue
import threading
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

_QUEUE: queue.Queue[dict] = queue.Queue(maxsize=1000)
_STARTED = threading.Event()
_LOCK = threading.Lock()


def usage_row(*, provider: str, model: str, response_model: str, scope: str, prompt_tokens, completion_tokens,
              reasoning_tokens) -> dict:
    """The stored row; the scope keeps only its kind (`kind:id` -> `kind`)."""
    def count(value) -> int:
        return value if isinstance(value, int) and value >= 0 else 0
    return {"occurred_at": datetime.now(UTC).isoformat(), "provider": provider[:40], "model": model[:80],
            "response_model": response_model[:80], "feature": (scope.split(":", 1)[0] or "none")[:60],
            "prompt_tokens": count(prompt_tokens), "completion_tokens": count(completion_tokens),
            "reasoning_tokens": count(reasoning_tokens)}


def record_usage(**fields) -> None:
    from app.platform.config import settings
    if not settings.AI_USAGE_LEDGER_ENABLED:
        return
    try:
        _QUEUE.put_nowait(usage_row(**fields))
    except queue.Full:
        logger.warning("ai usage ledger queue full; row dropped")
        return
    _start_writer()


def _start_writer() -> None:
    if _STARTED.is_set():
        return
    with _LOCK:
        if not _STARTED.is_set():
            threading.Thread(target=_write_forever, name="ai-usage-ledger", daemon=True).start()
            _STARTED.set()


def _write_forever() -> None:
    while True:
        row = _QUEUE.get()
        try:
            from app.platform.supabase import supabase_service
            supabase_service.schema("v3").table("ai_usage_events").insert(row).execute()
        except Exception as exc:
            logger.warning("ai usage ledger write failed error=%s", type(exc).__name__)
