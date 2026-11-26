"""Only a server-issued session UUID is published to the durable Celery broker."""
from app.platform.celery import celery_app
from app.modules.learning.application.session_events import TEXT_TTL_SECONDS


class CelerySessionEventQueue:
    def submit(self, session_id):
        celery_app.send_task("deeplingo.extract_speaking_events", args=[str(session_id)],
                             expires=TEXT_TTL_SECONDS, retry=False, ignore_result=True,
                             argsrepr="(<speaking session>,)")
