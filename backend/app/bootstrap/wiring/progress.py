"""Composition of the progress module."""
from app.bootstrap.wiring.clients import service_client
from app.modules.progress.application.service import ProgressService
from app.modules.progress.infrastructure.repositories import ProgressRepository


def get_progress_service() -> ProgressService:
    return ProgressService(store=ProgressRepository(service_client()))
