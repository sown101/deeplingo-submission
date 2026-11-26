"""Readers that feed the learner profile snapshot, scoped to one learning language."""
from app.bootstrap.wiring.clients import service_client
from app.modules.learner.application.profile_snapshot import LearnerProfileSnapshotService
from app.modules.learner.domain.agent_signals import SignalKind
from app.modules.learner.domain.profile_snapshot import GrammarSection, SignalsSection, VocabularySection
from app.modules.learner.infrastructure.profile_metrics import LearnerProfileMetricsRepository

MAX_CODES_PER_KIND = 5


class DeclaredLevel:
    def __init__(self, preferences):
        self.preferences = preferences

    def declared_level(self, user, language_code):
        preference = self.preferences.get_by_language_for_user(user_id=user.id, language_code=language_code)
        return preference.declared_level if preference else None


class Vocabulary:
    def __init__(self, coverage):
        self.coverage = coverage

    def vocabulary(self, user, language_code):
        for view in self.coverage.vocabulary(user):
            if view.language_code == language_code:
                return VocabularySection(known_words=view.known_words, library_words=view.library_words,
                                         is_estimate=view.is_estimate)
        return None


class Usage:
    """Saved words by usage rung; words the learner suspended are left out."""

    def __init__(self, targets):
        self.targets = targets

    def words_by_rung(self, user, language_code):
        counts: dict[int, int] = {}
        for row in self.targets.list_for_user(user.id, language_code=language_code):
            if row.get("status") == "suspended":
                continue
            rung = int(row.get("rung") or 0)
            counts[rung] = counts.get(rung, 0) + 1
        return counts


class Signals:
    """The closed-code signals the learner allowed; none at all unless consent is currently granted."""

    def __init__(self, service):
        self.service = service

    def signals(self, user, language_code):
        if not self.service.has_consent(user.id):
            return SignalsSection()
        rows = [item for item in self.service.signals(user.id).signals if item.language_code == language_code]

        def codes(kind: SignalKind) -> tuple[str, ...]:
            chosen = sorted((item for item in rows if item.kind == kind), key=lambda item: (-item.usage_count, item.code))
            return tuple(item.code for item in chosen)[:MAX_CODES_PER_KIND]

        return SignalsSection(error_kinds=codes(SignalKind.ERROR_TYPE), interests=codes(SignalKind.TOPIC),
                              goals=codes(SignalKind.GOAL))


class Grammar:
    """Grammar points practised at least once, over the approved banks of the learner's learning language."""

    def __init__(self, service):
        self.service = service

    def grammar_summary(self, user, language_code):
        total, by_level = self.service.practice_counts(user.id, language_code)
        if not by_level:
            return None
        return GrammarSection(practised_points=sum(by_level.values()), total_points=total, practised_by_level=by_level)


def get_learner_profile_snapshot_service() -> LearnerProfileSnapshotService:
    from app.bootstrap.wiring.practice import get_grammar_service
    from app.bootstrap.wiring.learner import get_agent_signals_service, get_video_coverage_service
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.learner.infrastructure.user_language_preferences import UserLanguagePreferenceRepository
    client = service_client()
    metrics = LearnerProfileMetricsRepository(client)
    return LearnerProfileSnapshotService(
        declared_level=DeclaredLevel(UserLanguagePreferenceRepository(client)),
        vocabulary=Vocabulary(get_video_coverage_service()),
        usage=Usage(SavedConceptRepository(client)),
        grammar=Grammar(get_grammar_service()),
        signals=Signals(get_agent_signals_service()),
        review=metrics,
        activity=metrics,
    )
