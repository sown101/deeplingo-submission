"""Content-only leased execution; PostgreSQL owns recovery, never Celery task IDs."""
import logging
from uuid import UUID

from app.platform.celery import celery_app
from app.platform.config import settings
from app.platform.llm.usage import usage_scope
from app.platform.supabase import supabase_service
from app.modules.content.domain.work_claims import StaleContentClaim
from app.modules.content.domain.failures import ContentFailure, ContentFailureClass
from app.modules.content.worker.failure_classification import classify_content_failure
from app.modules.content.application.preparation import LEARNING_PREPARATION_VERSION
from app.modules.content.application.region_preparation import REGION_PREPARATION_VERSION
from app.modules.content.worker.dispatch import ContentWorkDispatcher
from app.bootstrap.wiring.content import (
    build_content_ingestion_service,
    build_learning_content_preparation_service,
    build_region_preparation_service,
    build_work_intents,
)

logger = logging.getLogger(__name__)


def _not_claimed(intent_id, status="not_claimed"):
    return {"status": status, "work_intent_id": intent_id}


def _claim(intents, persistent_id, stage):
    try:
        intent = intents.get(persistent_id)
        if intent is None or intent.stage != stage:
            return None
        parameters = {"lease_seconds": settings.CONTENT_WORK_LEASE_SECONDS}
        if stage == "learning_preparation":
            parameters["preparation_version"] = LEARNING_PREPARATION_VERSION
        elif stage == "region_preparation":
            # The claim RPC refuses (terminally) a region admitted under another version.
            parameters["preparation_version"] = REGION_PREPARATION_VERSION
        return intents.claim(persistent_id, **parameters)
    except Exception:
        # No known ownership: never manufacture a failure write. Pending work is
        # rediscovered; a committed-but-lost claim receipt expires under the budget.
        logger.warning("Content claim unavailable intent_id=%s stage=%s", persistent_id, stage)
        return None




def _failure(intents, claim, *, failure):
    # PostgreSQL owns the total claim budget and due time, including worker loss.
    try:
        status = intents.record_failure(claim, failure_code=failure.code,
            failure_class=failure.category.value, explicit_retry=failure.explicit_retry)
    except StaleContentClaim:
        logger.info("Content stale failure rejected intent_id=%s epoch=%s", claim.intent_id, claim.epoch)
        return _not_claimed(str(claim.intent_id), "stale_claim")
    except Exception:
        # Failure commit may be unknown. No unfenced fallback or blind append retry;
        # Beat reloads authoritative state and eventually recovers an expired owner.
        logger.warning("Content failure outcome unknown intent_id=%s epoch=%s", claim.intent_id, claim.epoch)
        return _not_claimed(str(claim.intent_id), "failure_reconciliation_pending")
    logger.info("Content failure intent_id=%s stage=%s generation=%s epoch=%s class=%s code=%s state=%s",
        claim.intent_id, claim.stage, claim.generation, claim.epoch, failure.category.value, failure.code, status)
    if status == "pending":
        return _not_claimed(str(claim.intent_id), "retry_scheduled")
    if status != "failed":
        return _not_claimed(str(claim.intent_id), "failure_reconciliation_pending")
    return {"status": "failed", "video_id": str(claim.video_id),
            "work_intent_id": str(claim.intent_id), "failure_code": failure.code,
            "retryable": failure.explicit_retry}


@celery_app.task(bind=True, name="deeplingo.process_prepared_video_v3", max_retries=0,
                 soft_time_limit=1500, time_limit=1800)
def process_prepared_video_v3(self, work_intent_id: str):
    if not supabase_service:
        raise RuntimeError("Supabase service client is not configured")
    intents = build_work_intents(supabase_service)
    persistent_id = UUID(work_intent_id)
    claim = _claim(intents, persistent_id, "transcript")
    if claim is None:
        return _not_claimed(work_intent_id)
    logger.info("Content claim intent_id=%s stage=%s generation=%s epoch=%s lease_expires_at=%s",
                claim.intent_id, claim.stage, claim.generation, claim.epoch, claim.lease_expires_at.isoformat())
    try:
        service = build_content_ingestion_service(supabase_service, claim=claim)
        result = service.process_video(claim.video_id, processing_already_claimed=True,
                                       work_intent_id=persistent_id, execution_claim=claim)
    except StaleContentClaim:
        logger.info("Content stale success rejected intent_id=%s epoch=%s", persistent_id, claim.epoch)
        return _not_claimed(work_intent_id, "stale_claim")
    except Exception as exc:
        return _failure(intents, claim, failure=classify_content_failure(exc))
    try:
        preparation = intents.active_for_video(video_id=claim.video_id, stage="learning_preparation")
        if preparation is not None:
            ContentWorkDispatcher(intents).dispatch(preparation.id)
    except Exception:
        logger.warning("Preparation fast-path dispatch unavailable video_id=%s", claim.video_id)
    return {"status": "ready", "video_id": str(claim.video_id),
            "work_intent_id": work_intent_id, "segments": len(result.segments)}


@celery_app.task(bind=True, name="deeplingo.prepare_video_learning_content", max_retries=0,
                 soft_time_limit=1500, time_limit=1800)
def prepare_video_learning_content(self, work_intent_id: str):
    if not supabase_service:
        raise RuntimeError("Supabase service client is not configured")
    intents = build_work_intents(supabase_service)
    persistent_id = UUID(work_intent_id)
    claim = _claim(intents, persistent_id, "learning_preparation")
    if claim is None:
        return _not_claimed(work_intent_id)
    logger.info("Content claim intent_id=%s stage=%s generation=%s epoch=%s lease_expires_at=%s",
                claim.intent_id, claim.stage, claim.generation, claim.epoch, claim.lease_expires_at.isoformat())
    try:
        service = build_learning_content_preparation_service(supabase_service, claim=claim)
        outcome = service.prepare_claimed(claim.video_id, persist_terminal=False)
        if outcome.status != "failed":
            intents.finish_preparation(claim, status=outcome.status, usable_count=outcome.usable_count,
                                       support_language_code=service.support_language_code if outcome.usable_count else None,
                                       failure_code=outcome.failure_code)
    except StaleContentClaim:
        logger.info("Content stale completion rejected intent_id=%s epoch=%s", persistent_id, claim.epoch)
        return _not_claimed(work_intent_id, "stale_claim")
    except Exception as exc:
        return _failure(intents, claim, failure=classify_content_failure(exc))
    if outcome.status == "failed":
        # Provider/transport errors propagate from the async factory. A completed
        # failed outcome here represents rejected/missing trusted usable content.
        return _failure(intents, claim, failure=ContentFailure(ContentFailureClass.PERMANENT, "validation_failed"))
    return {"status": outcome.status, "video_id": str(claim.video_id),
            "work_intent_id": work_intent_id, "usable_count": outcome.usable_count,
            "failure_code": outcome.failure_code}


@celery_app.task(bind=True, name="deeplingo.prepare_video_region", max_retries=0,
                 soft_time_limit=1500, time_limit=1800)
def prepare_video_region(self, work_intent_id: str):
    """M1 S2: prepare one study region; the region row, never the Video, records the outcome."""
    if not supabase_service:
        raise RuntimeError("Supabase service client is not configured")
    intents = build_work_intents(supabase_service)
    persistent_id = UUID(work_intent_id)
    claim = _claim(intents, persistent_id, "region_preparation")
    if claim is None:
        return _not_claimed(work_intent_id)
    logger.info("Content claim intent_id=%s stage=%s generation=%s epoch=%s region_id=%s lease_expires_at=%s",
                claim.intent_id, claim.stage, claim.generation, claim.epoch, claim.region_preparation_id,
                claim.lease_expires_at.isoformat())
    try:
        service = build_region_preparation_service(supabase_service, claim=claim)
        with usage_scope("region_preparation", claim.region_preparation_id):  # M1 S7 log
            outcome = service.prepare_claimed(claim)
        if outcome.status != "failed":
            intents.finish_region_preparation(claim, status=outcome.status, usable_count=outcome.usable_count,
                                              failure_code=outcome.failure_code)
    except StaleContentClaim:
        logger.info("Content stale completion rejected intent_id=%s epoch=%s", persistent_id, claim.epoch)
        return _not_claimed(work_intent_id, "stale_claim")
    except Exception as exc:
        return _failure(intents, claim, failure=classify_content_failure(exc))
    if outcome.status == "failed":
        return _failure(intents, claim, failure=ContentFailure(ContentFailureClass.PERMANENT, "validation_failed"))
    return {"status": outcome.status, "video_id": str(claim.video_id),
            "region_preparation_id": str(claim.region_preparation_id),
            "work_intent_id": work_intent_id, "usable_count": outcome.usable_count}


@celery_app.task(name="deeplingo.reconcile_content_work_intents")
def reconcile_content_work_intents():
    if not supabase_service:
        raise RuntimeError("Supabase service client is not configured")
    intents = build_work_intents(supabase_service)
    recovered = intents.recover_expired(limit=50)
    scanned, dispatched = ContentWorkDispatcher(intents).reconcile_due(limit=50)
    logger.info("Content reconcile recovered=%s scanned=%s dispatched=%s", recovered, scanned, dispatched)
    return {"recovered": recovered, "scanned": scanned, "dispatched": dispatched}
