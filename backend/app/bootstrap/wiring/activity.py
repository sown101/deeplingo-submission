"""Composition of the learning log and study requests (activity module)."""
from app.bootstrap.wiring.clients import service_client
from app.modules.activity.application.service import ActivityService
from app.modules.activity.infrastructure.repositories import ActivityLogRepository, StudyRequestRepository


def build_activity_service(client) -> ActivityService:
    """The one ActivityService every flow records through."""
    return ActivityService(log=ActivityLogRepository(client), requests=StudyRequestRepository(client))


def get_activity_service() -> ActivityService:
    return build_activity_service(service_client())
