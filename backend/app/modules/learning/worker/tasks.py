"""M1 S7b: retention of speech transcripts (FR-3.11) and pronunciation scores after 12 months. The practice
log is no longer purged: it is kept until the learner deletes it or their account (PRD 8.10).

Expired rows are already unreadable (row policy and every service read filter on expiry); this
deletes them for every learner, including learners who never come back, in bounded batches.
"""
import logging

from app.platform.celery import celery_app
from app.platform.supabase import supabase_service

logger = logging.getLogger(__name__)

PURGE_BATCH = 1000
MAX_BATCHES = 5


@celery_app.task(name="deeplingo.purge_expired_learner_data")
def purge_expired_learner_data():
    if not supabase_service:
        raise RuntimeError("Supabase service client is not configured")
    totals = {"speech_transcripts": 0, "pronunciation_scores": 0}
    for _ in range(MAX_BATCHES):
        result = supabase_service.schema("v3").rpc("purge_expired_learner_data", {"p_limit": PURGE_BATCH}).execute()
        deleted = result.data or {}
        for key in totals:
            totals[key] += int(deleted.get(key, 0))
        if all(int(deleted.get(key, 0)) < PURGE_BATCH for key in totals):
            break
    logger.info("Learner data purge speech_transcripts=%s pronunciation_scores=%s",
                totals["speech_transcripts"], totals["pronunciation_scores"])
    return totals


@celery_app.task(name="deeplingo.extract_speaking_events", bind=True, ignore_result=True,
                 soft_time_limit=45, time_limit=60, max_retries=2,
                 acks_late=True, reject_on_worker_lost=True)
def extract_speaking_events(self, session_id):
    from uuid import UUID
    from app.bootstrap.wiring.session_events import get_session_events_service
    service = get_session_events_service()
    if service is None:
        return {"status": "disabled"}
    result = service.process(UUID(session_id))
    if result["status"] == "projection_pending":
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=5)
        service.fail_projection(UUID(session_id))
        return {"status": "failed"}
    return result
