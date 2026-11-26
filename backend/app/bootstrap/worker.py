"""Celery worker composition root: run with ``celery -A app.bootstrap.worker``."""
from celery.signals import after_setup_logger, after_setup_task_logger, worker_process_shutdown

from app.platform.celery import celery_app
from app.platform.logging import install_redaction


celery_app.conf.update(
    imports=("app.modules.content.worker.tasks", "app.modules.learning.worker.tasks"),
    beat_schedule={
        "reconcile-content-work-intents": {
            "task": "deeplingo.reconcile_content_work_intents",
            "schedule": 60.0,
        },
        # 12-month retention of kept speech transcripts and pronunciation scores, for every learner.
        "purge-expired-learner-data": {
            "task": "deeplingo.purge_expired_learner_data",
            "schedule": 3600.0,
        },
    },
)


@worker_process_shutdown.connect
def close_worker_process_clients(**kwargs):
    from app.platform.supabase import close_process_clients
    close_process_clients()


@after_setup_logger.connect
@after_setup_task_logger.connect
def redact_worker_logs(logger=None, **kwargs):
    # Celery installs its own handlers; wrap them so worker logs get the SEC-07 redaction too.
    install_redaction(logger)
