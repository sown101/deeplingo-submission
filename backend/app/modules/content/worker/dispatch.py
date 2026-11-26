"""Single broker publication path for durable Content V3 work intents."""

import logging
from collections.abc import Callable
from uuid import UUID

from app.modules.content.domain.work_intents import VideoWorkIntent
from app.modules.content.application.store_ports import VideoWorkIntentStore


logger = logging.getLogger(__name__)


def _publish(intent: VideoWorkIntent) -> str:
    # Import lazily: the worker imports this adapter for post-commit handoff.
    from app.modules.content.worker.tasks import (
        prepare_video_learning_content,
        prepare_video_region,
        process_prepared_video_v3,
    )

    task = (
        process_prepared_video_v3 if intent.stage == "transcript"
        else prepare_video_learning_content if intent.stage == "learning_preparation"
        else prepare_video_region if intent.stage == "region_preparation"
        else None
    )
    if task is None:
        raise ValueError("Unsupported Content work stage")
    from app.platform.celery import celery_app
    from app.platform.config import settings

    # PostgreSQL already accepted this work. Do not borrow an unbounded shared
    # broker pool or stack transport retries onto durable Beat redispatch.
    # These are per-I/O bounds, not an end-to-end HTTP/DNS deadline.
    options = {
        **celery_app.conf.broker_transport_options,
        "socket_connect_timeout": settings.CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": settings.CONTENT_PUBLISH_SOCKET_TIMEOUT_SECONDS,
        "retry_on_timeout": False,
        "max_retries": 0,
        "connect_retries_timeout": settings.CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS,
    }
    with celery_app.connection_for_write(
        connect_timeout=settings.CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS,
        transport_options=options,
    ) as connection:
        receipt = task.apply_async(args=[str(intent.id)], connection=connection, retry=False)
    return str(receipt.id)


class ContentWorkDispatcher:
    def __init__(
        self,
        intents: VideoWorkIntentStore,
        *,
        publish: Callable[[VideoWorkIntent], str] | None = None,
    ):
        self.intents = intents
        self.publish = publish or _publish

    def dispatch(self, intent_id: UUID) -> bool:
        intent = self.intents.get(intent_id)
        if intent is None or intent.state not in {"pending", "dispatched"}:
            return False
        try:
            task_id = self.publish(intent)
        except Exception:
            logger.warning(
                "Content work publish unavailable intent_id=%s video_id=%s stage=%s generation=%s",
                intent.id, intent.video_id, intent.stage, intent.generation,
            )
            try:
                self.intents.record_dispatch(intent.id, accepted=False)
            except Exception:
                logger.error("Content work publish-failure metadata unavailable intent_id=%s", intent.id)
            return False
        try:
            self.intents.record_dispatch(intent.id, accepted=True)
        except Exception:
            # Publish may already have succeeded. The due scanner may republish;
            # one intent and the worker's conditional claim make that expected.
            logger.error("Content work publish ACK metadata unavailable intent_id=%s task_id=%s", intent.id, task_id)
        return True

    def reconcile_due(self, *, limit: int = 50) -> tuple[int, int]:
        due = self.intents.due(limit=limit)
        dispatched = 0
        for intent in due:
            if self.dispatch(intent.id):
                dispatched += 1
        return len(due), dispatched
