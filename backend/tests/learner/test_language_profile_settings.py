"""L1a: the learner's declared level and daily new limit live on the language profile."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.commands import LearnerLanguageProfileUpdate
from app.modules.learner.application.learner_model import LearnerModelError, LearnerModelService
from app.modules.learner.domain.models import UserLanguagePreference

USER = CurrentUser(id=UUID("22222222-2222-2222-2222-222222222222"), role="authenticated", claims={})


class Preferences:
    def __init__(self):
        self.calls: list[dict] = []

    def upsert_profile_for_user(self, *, user_id, learning_language, support_language, **kwargs):
        self.calls.append(kwargs)
        return UserLanguagePreference(user_id=user_id, language_code=learning_language,
                                      support_language_code=support_language, **kwargs.get("extra", {}))


def build():
    preferences = Preferences()
    service = LearnerModelService(
        profiles=Mock(), languages=SimpleNamespace(get_active=lambda code: object()),
        language_preferences=preferences)
    return service, preferences


def update(service, learning="en", **extra):
    return service.update_language_profile(
        USER, LearnerLanguageProfileUpdate(learning_language=learning, support_language="vi", **extra))


def test_an_update_without_the_new_fields_sends_nothing_extra_and_keeps_the_defaults():
    service, preferences = build()
    profile = update(service)
    assert preferences.calls == [{}]
    assert (profile.declared_level, profile.daily_new_limit) == (None, 10)


def test_a_declared_level_is_normalised_for_the_learning_language_and_a_limit_is_stored():
    service, preferences = build()
    profile = update(service, declared_level="b1+", daily_new_limit=15)
    assert preferences.calls == [{"extra": {"declared_level": "B1+", "daily_new_limit": 15}}]
    assert (profile.declared_level, profile.daily_new_limit) == ("B1+", 15)
    assert update(service, learning="zh", declared_level="hsk 3").declared_level == "HSK3"


def test_an_empty_declared_level_clears_it():
    service, preferences = build()
    update(service, declared_level="")
    assert preferences.calls == [{"extra": {"declared_level": None}}]


@pytest.mark.parametrize("learning, level", [("en", "HSK3"), ("zh", "B1"), ("en", "C2"), ("zh", "HSK7"), ("en", "nonsense")])
def test_a_level_from_the_wrong_scale_or_outside_the_declarable_levels_is_refused(learning, level):
    service, preferences = build()
    with pytest.raises(LearnerModelError):
        update(service, learning=learning, declared_level=level)
    assert preferences.calls == []


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_a_daily_limit_outside_one_to_fifty_is_refused(limit):
    service, preferences = build()
    with pytest.raises(LearnerModelError):
        update(service, daily_new_limit=limit)
    assert preferences.calls == []
