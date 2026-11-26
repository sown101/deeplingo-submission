"""Composition of L2 post-session extraction: on when its non-persistent Redis instance is configured."""
from functools import lru_cache

from redis import Redis

from app.bootstrap.wiring.clients import service_client
from app.bootstrap.wiring.learner import get_agent_signals_service, get_word_targets_service
from app.bootstrap.wiring.speaking import _language_model
from app.modules.learning.application.session_events import SessionEventsService
from app.modules.learning.infrastructure.session_events import RedisSessionText, SpeakingSessionRepository
from app.modules.learning.infrastructure.session_event_queue import CelerySessionEventQueue
from app.modules.review.application.speaking_review import SpeakingReviewService
from app.modules.review.infrastructure.speaking_reviews import SpeakingReviewRepository
from app.modules.review.infrastructure.fsrs_adapter import FSRSAdapter
from app.platform.config import settings


@lru_cache(maxsize=1)
def get_session_events_service():
    if not settings.COMPANION_SESSION_TEXT_REDIS_URL:
        return None
    redis = Redis.from_url(settings.COMPANION_SESSION_TEXT_REDIS_URL, decode_responses=True,
                           socket_connect_timeout=2, socket_timeout=2)
    return SessionEventsService(
        store=SpeakingSessionRepository(service_client()), text=RedisSessionText(redis),
        queue=CelerySessionEventQueue(),
        model=_language_model(settings.COMPANION_SESSION_EVENTS_MODEL or settings.AI_EXTRACTION_MODEL),
        rungs=get_word_targets_service(),
        consent=get_agent_signals_service(),
        reviews=SpeakingReviewService(store=SpeakingReviewRepository(service_client()), adapter=FSRSAdapter()),
    )
