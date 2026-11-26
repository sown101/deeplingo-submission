"""Codex review (2026-11-05): JAM and Shadowing send audio to Azure, so they need the learner's
voice consent like the agent (PRD FR-3.4). No live AI or speech service: fakes only."""

import pytest

from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.speaking_ports import SpeakingPracticeError

from tests.learning.test_speaking_services_and_api import OWNER, shadowing, speech  # noqa: F401


class Consent:
    def __init__(self, granted):
        self.granted, self.calls = granted, 0

    def has_consent(self, user_id):
        self.calls += 1
        return self.granted


def refused(callable_):
    with pytest.raises(SpeakingPracticeError) as raised:
        callable_()
    return raised.value.kind, raised.value.code


def test_shadowing_without_voice_consent_never_reaches_the_assessor(shadowing):  # noqa: F811
    shadowing.service.consent = Consent(False)
    assert refused(lambda: shadowing.service.assess(CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id,
                                                    speech())) == ("conflict", "voice_consent_required")
    assert shadowing.assessor.calls == []


def test_shadowing_with_voice_consent_is_assessed(shadowing):  # noqa: F811
    shadowing.service.consent = Consent(True)
    shadowing.service.assess(CurrentUser(id=OWNER), shadowing.item, shadowing.segment_id, speech())
    assert shadowing.assessor.calls
