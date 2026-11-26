from uuid import UUID

from app.modules.learner.domain.profile_snapshot import ActivitySection, ReviewSection
from app.platform.persistence import V3Repository, cached_read


class LearnerProfileMetricsRepository(V3Repository):
    table_name = "learner_profile_metrics"

    @cached_read
    def _metrics(self, user_id: UUID, language_code: str) -> dict:
        return self.client.schema(self.schema).rpc("learner_profile_metrics", {
            "p_user_id": str(user_id), "p_language_code": language_code,
        }).execute().data

    def review_summary(self, user, language_code: str) -> ReviewSection:
        row = self._metrics(user.id, language_code)
        return ReviewSection.build(cards=row["cards"], due_now=row["due_now"], lapses=row["lapses"])

    def activity_summary(self, user, language_code: str) -> ActivitySection:
        row = self._metrics(user.id, language_code)
        return ActivitySection(streak_days=row["streak_days"], minutes_last_7_days=row["minutes_last_7_days"])
