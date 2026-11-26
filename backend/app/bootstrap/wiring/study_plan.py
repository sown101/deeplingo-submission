"""Composition of the daily study plan.

The plan reads review readiness (review module), saved words (learner module) and companion
recurring error kinds (learner module) through learning-owned ports; adapters below bridge the services.
"""
from __future__ import annotations

from app.bootstrap.wiring.activity import build_activity_service
from app.bootstrap.wiring.clients import service_client
from app.bootstrap.wiring.content import get_video_workspace_service
from app.bootstrap.wiring.learner import get_agent_signals_service, get_my_words_service
from app.bootstrap.wiring.agent import PersonalizationSignals
from app.bootstrap.wiring.speaking import _DueInLanguage, _language_model
from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
from app.modules.content.infrastructure.repositories.learner_videos import LearnerVideoRepository
from app.modules.content.infrastructure.repositories.videos import VideoRepository
from app.modules.learner.domain.concept_lists import ConceptList
from app.modules.learner.infrastructure.user_language_preferences import UserLanguagePreferenceRepository
from app.modules.learning.application.study_plan import StudyPlanService
from app.modules.learning.infrastructure.speaking_activity import SpeakingSessions
from app.modules.learning.infrastructure.study_plans import StudyPlanRepository
from app.modules.review.infrastructure.review_states import ReviewStateRepository
from app.platform.config import settings

# Enough to size a review proposal.
REVIEW_COUNT_CAP = 20


class _ReviewReadiness:
    """Cards due now or overdue whose Concept is in the plan's language, capped to what sizes a proposal."""

    def __init__(self, due_in_language):
        self.due_in_language = due_in_language

    def ready_count(self, user, *, language_code: str) -> int:
        return min(self.due_in_language.ready_count(user, language_code=language_code), REVIEW_COUNT_CAP)


class _SavedWordCount:
    def __init__(self, my_words):
        self.my_words = my_words

    def saved_to_practise(self, user, *, language_code: str) -> int:
        words = self.my_words.list(user, language_code).words
        return sum(1 for word in words if word.list == ConceptList.SAVED)


class _ResumeVideo:
    """The learner's latest video with a saved position or study part (content module data)."""

    def __init__(self, workspace):
        self.workspace = workspace

    def latest(self, user):
        return self.workspace.continue_learning(user).item


def get_study_plan_service() -> StudyPlanService:
    client = service_client()
    return StudyPlanService(
        preferences=UserLanguagePreferenceRepository(client),
        library=LearnerVideoRepository(client),
        videos=VideoRepository(client),
        reviews=_ReviewReadiness(_DueInLanguage(ReviewStateRepository(client), ConceptRepository(client))),
        saved_words=_SavedWordCount(get_my_words_service()),
        model=_language_model(settings.COMPANION_MODEL or settings.SPEAKING_COACH_MODEL),
        store=StudyPlanRepository(client),
        recurring=PersonalizationSignals(get_agent_signals_service()),
        resume=_ResumeVideo(get_video_workspace_service()),
        speaking=SpeakingSessions(build_activity_service(client)),
    )
