
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.views import (
    LearnerLanguageProfile,
    LearnerInitializationResult,
)
from app.modules.learner.application.commands import LearnerLanguageProfileUpdate
from app.modules.learner.domain.levels import declarable_levels, normalize_level
from app.modules.learner.domain.word_targets import validate_daily_new_limit
from app.modules.learner.domain.models import Profile, UserLanguagePreference
from app.modules.learner.application.ports import (
    LanguagePreferenceStore,
    LanguageReader,
    ProfileStore,
)


class LearnerModelError(ValueError):
    pass


class LearnerModelService:
    def __init__(
        self,
        *,
        profiles: ProfileStore,
        languages: LanguageReader,
        language_preferences: LanguagePreferenceStore,
    ):
        self.profiles = profiles
        self.languages = languages
        self.language_preferences = language_preferences

    def get_profile(self, current_user: CurrentUser) -> Profile | None:
        return self.profiles.get_by_user_id(current_user.id)

    def get_language_profile(self, current_user: CurrentUser) -> LearnerLanguageProfile:
        preference = self.language_preferences.get_profile_for_user(current_user.id)
        if preference is None:
            return LearnerLanguageProfile()
        return self._language_profile(preference)

    def update_language_profile(
        self,
        current_user: CurrentUser,
        request: LearnerLanguageProfileUpdate,
    ) -> LearnerLanguageProfile:
        for language_code in (request.learning_language, request.support_language):
            if self.languages.get_active(language_code) is None:
                raise LearnerModelError(f"Unknown or inactive language: {language_code}")
        extra: dict = {}
        if request.declared_level is not None:
            if request.declared_level.strip() == "":
                extra["declared_level"] = None
            else:
                level = normalize_level(request.learning_language, request.declared_level)
                if level is None or level not in declarable_levels(request.learning_language):
                    raise LearnerModelError(
                        f"declared_level is not a level of the {request.learning_language} scale")
                extra["declared_level"] = level
        if request.daily_new_limit is not None:
            try:
                extra["daily_new_limit"] = validate_daily_new_limit(request.daily_new_limit)
            except ValueError as exc:
                raise LearnerModelError(str(exc)) from exc
        kwargs = {"extra": extra} if extra else {}
        preference = self.language_preferences.upsert_profile_for_user(
            user_id=current_user.id,
            learning_language=request.learning_language,
            support_language=request.support_language,
            **kwargs,
        )
        return self._language_profile(preference)

    def initialize(
        self,
        current_user: CurrentUser,
        *,
        language_codes: list[str],
        create_profile: bool = True,
    ) -> LearnerInitializationResult:
        profile_status = "skipped"
        if create_profile:
            existing_profile = self.profiles.get_by_user_id(current_user.id)
            if existing_profile is None:
                self.profiles.upsert_current_user(current_user.id)
                profile_status = "created"
            else:
                profile_status = "reused"

        if not language_codes:
            language_codes = [pref.language_code for pref in self.language_preferences.list_for_user(current_user.id)]

        for language_code in _normalize_language_codes(language_codes):
            if self.languages.get_active(language_code) is None:
                raise LearnerModelError(f"Unknown or inactive language: {language_code}")

        return LearnerInitializationResult(user_id=current_user.id, profile_status=profile_status)

    @staticmethod
    def _language_profile(preference: UserLanguagePreference) -> LearnerLanguageProfile:
        support_language = preference.support_language_code
        return LearnerLanguageProfile(
            learning_language=preference.language_code,
            support_language=support_language,
            is_complete=bool(preference.language_code and support_language),
            declared_level=preference.declared_level,
            daily_new_limit=preference.daily_new_limit,
        )


def _normalize_language_codes(language_codes: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for code in language_codes:
        language_code = (code or "").strip().casefold()
        if not language_code:
            raise LearnerModelError("language_codes cannot contain empty values")
        if language_code not in seen:
            seen.add(language_code)
            normalized.append(language_code)
    return normalized
