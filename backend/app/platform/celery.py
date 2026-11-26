from celery import Celery

from app.platform.config import settings


# Technical Celery configuration only. Task modules, the beat schedule and worker
# process lifecycle hooks are composed in app.bootstrap.worker (the -A entrypoint).
celery_app = Celery("deeplingo", broker=settings.REDIS_URL or None)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    worker_concurrency=2,
    worker_pool="prefork",  # Supported Content runtime: Linux; Windows threads unqualified.
    worker_prefetch_multiplier=1,
)
