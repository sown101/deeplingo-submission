"""Intentional learner targets, level warnings and the usage ladder.

All saved targets are immediately eligible for review. Daily-limit fields remain
in the API for compatibility while the web is updated.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.content.contracts import Concept
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.ports import (
    LanguagePreferenceStore,
    ProfileStore,
    TargetEventStore,
    TargetStore,
)
from app.modules.learner.domain.ladder import EventKind, Outcome, TargetEvent, rung_from_events
from app.modules.learner.domain.levels import is_above_level, normalize_level
from app.modules.learner.domain.word_targets import (
    DEFAULT_DAILY_NEW_LIMIT,
    TargetStatus,
    local_day_start,
    resolve_timezone,
)

logger = logging.getLogger(__name__)


class WordTargetsError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str, extra: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.extra = extra or {}
        super().__init__(message)


class TargetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared_level: str | None = None
    daily_new_limit: int = DEFAULT_DAILY_NEW_LIMIT


class TargetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backlog: int = 0
    active: int = 0
    suspended: int = 0
    activated_today: int = 0
    daily_new_limit: int = DEFAULT_DAILY_NEW_LIMIT
    declared_level: str | None = None


class WordTargetsService:
    def __init__(self, *, targets: TargetStore, events: TargetEventStore,
                 preferences: LanguagePreferenceStore, profiles: ProfileStore,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.targets = targets
        self.events = events
        self.preferences = preferences
        self.profiles = profiles
        self.clock = clock

    # --- Settings and levels ---------------------------------------------------------------

    def settings(self, user_id: UUID, language_code: str) -> TargetSettings:
        preference = self.preferences.get_by_language_for_user(user_id=user_id, language_code=language_code)
        if preference is None:
            return TargetSettings()
        return TargetSettings(
            declared_level=normalize_level(language_code, getattr(preference, "declared_level", None)),
            daily_new_limit=getattr(preference, "daily_new_limit", None) or DEFAULT_DAILY_NEW_LIMIT,
        )

    @staticmethod
    def level_of(concept: Concept) -> str | None:
        return normalize_level(concept.language_code, concept.difficulty_level)

    def check_level(self, user_id: UUID, concept: Concept, *, acknowledged: bool) -> None:
        """Warns, never blocks: an explicit add of a word more than one band above the learner's declared
        level needs one confirmation (`acknowledge_above_level`). Existing targets are never re-checked."""
        if acknowledged or self.targets.get(user_id, concept.id) is not None:
            return
        level = self.level_of(concept)
        declared = self.settings(user_id, concept.language_code).declared_level
        if is_above_level(concept.language_code, level, declared):
            raise WordTargetsError(
                "This word is above your level.", status_code=409, code="above_level",
                extra={"level": level, "declared_level": declared},
            )

    # --- Registering targets ---------------------------------------------------------------

    def register(self, user: CurrentUser, concept: Concept, *, save_source: str, explicit: bool, priority: int,
                 source_learning_object_id: UUID | None = None, acknowledge_above_level: bool = False) -> dict:
        if concept.id is None:
            raise WordTargetsError("This word cannot be saved right now.", status_code=503, code="word_unavailable")
        if explicit:
            self.check_level(user.id, concept, acknowledged=acknowledge_above_level)
        return self.targets.save(
            user.id, concept_id=concept.id, save_source=save_source, source_learning_object_id=source_learning_object_id,
            language_code=concept.language_code, level_label=self.level_of(concept), priority=priority,
            explicit=explicit,
        )

    def set_status(self, user: CurrentUser, concept_id: UUID, status: TargetStatus) -> dict:
        """Pause or resume a target; legacy backlog requests mean active."""
        effective = TargetStatus.ACTIVE if status == TargetStatus.BACKLOG else status
        row = self.targets.set_status(user.id, concept_id=concept_id, status=effective.value, now=self.clock())
        if row is None:
            raise WordTargetsError("Word not found.", status_code=404, code="word_not_found")
        return row

    # --- Summary ---------------------------------------------------------------------------

    def summary(self, user_id: UUID, language_code: str, statuses: list[str]) -> TargetSummary:
        settings = self.settings(user_id, language_code)
        since = local_day_start(self.clock(), self._timezone_name(user_id))
        counts = {status.value: 0 for status in TargetStatus}
        for status in statuses:
            effective = "active" if status == "backlog" else status
            counts[effective] = counts.get(effective, 0) + 1
        return TargetSummary(
            backlog=counts["backlog"], active=counts["active"], suspended=counts["suspended"],
            activated_today=self.targets.count_activated_since(user_id, language_code=language_code, since=since),
            daily_new_limit=settings.daily_new_limit, declared_level=settings.declared_level,
        )

    # --- Events and the ladder -------------------------------------------------------------

    def _refresh_rung(self, user_id: UUID, concept_id: UUID) -> int | None:
        if self.targets.get(user_id, concept_id) is None:
            return None
        tz = resolve_timezone(self._timezone_name(user_id))
        history = [
            TargetEvent(kind=EventKind(row["kind"]), outcome=Outcome(row["outcome"]),
                        occurred_at=_parse_time(row["occurred_at"]) or self.clock(), context_key=row.get("context_key"))
            for row in self.events.list_for_concept(user_id, concept_id)
        ]
        rung = rung_from_events(history, tz)
        self.targets.set_rung(user_id, concept_id=concept_id, rung=rung)
        return rung

    def refresh_rung(self, user_id: UUID, concept_id: UUID, *, strict: bool = False) -> None:
        """Recompute the stored rung from review and speaking events. Strict mode lets speaking retry the projection."""
        try:
            self._refresh_rung(user_id, concept_id)
        except Exception:  # noqa: BLE001 - the answer and its event are already committed
            if strict:
                raise
            logger.warning("target rung not refreshed concept_id=%s", concept_id, exc_info=True)

    def _timezone_name(self, user_id: UUID) -> str | None:
        profile = self.profiles.get_by_user_id(user_id)
        return profile.timezone if profile is not None else None


def _parse_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
