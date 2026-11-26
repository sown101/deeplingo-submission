"""FR-3.4 / FR-3.6: one revocable voice consent and structured personalization signals."""
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_agent_signals_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.agent_signals import AgentSignalsService
from app.modules.learner.domain.agent_signals import (
    ALLOWED_CODES,
    AgentConsent,
    PersonalizationSignal,
    SignalKind,
    consent_status,
)

USER, OTHER = uuid4(), uuid4()
URL = "/api/v1/v3/learner/me/agent"
MIGRATION = next(Path(__file__).parents[2].glob("supabase/migrations/*_agent_consent_signals.sql"))


class FakeConsents:
    def __init__(self, granted=None):
        self.rows = {} if granted is None else {USER: AgentConsent(user_id=USER, voice_consent=granted)}

    def get(self, user_id):
        return self.rows.get(user_id)

    def set(self, user_id, granted):
        self.rows[user_id] = AgentConsent(user_id=user_id, voice_consent=granted, decided_at=datetime.now(UTC))
        return self.rows[user_id]


class FakeSignals:
    def __init__(self, signals=()):
        self.rows = list(signals)

    def list_all(self, user_id):
        return [row for row in self.rows if row.user_id == user_id]

    def record(self, user_id, *, language_code, kind, code, replace_kind):
        if replace_kind:
            self.rows = [row for row in self.rows if not (row.user_id == user_id and row.kind == kind
                                                          and row.language_code == language_code)]
        for row in self.rows:
            if (row.user_id, row.language_code, row.kind, row.code) == (user_id, language_code, kind, code):
                row.usage_count += 1
                return row
        row = PersonalizationSignal(id=uuid4(), user_id=user_id, language_code=language_code, kind=kind,
                                    code=code, updated_at=datetime.now(UTC))
        self.rows.append(row)
        return row

    def delete_one(self, user_id, signal_id):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not (row.user_id == user_id and row.id == signal_id)]
        return len(self.rows) < before

    def delete_all(self, user_id):
        self.rows = [row for row in self.rows if row.user_id != user_id]


def signal(kind, code, *, user=USER, language="en"):
    return PersonalizationSignal(id=uuid4(), user_id=user, language_code=language, kind=kind, code=code,
                                 updated_at=datetime.now(UTC))


def service(granted=True, signals=()):
    return AgentSignalsService(consents=FakeConsents(granted), signals=FakeSignals(signals))


def test_consent_is_ask_until_the_learner_decides_then_granted_or_revoked():
    assert consent_status(None) == "ask"
    assert service(granted=None).consent(USER).status == "ask"
    assert service(granted=True).consent(USER).status == "granted"
    assert service(granted=False).consent(USER).status == "revoked"


def test_one_consent_can_be_granted_then_revoked_and_revoking_keeps_the_signals_the_learner_may_delete():
    agent = service(granted=None, signals=[signal(SignalKind.TOPIC, "travel")])
    assert agent.set_consent(USER, True).status == "granted" and agent.has_consent(USER)
    view = agent.set_consent(USER, False)
    assert view.status == "revoked" and view.decided_at is not None and not agent.has_consent(USER)
    assert [item.code for item in agent.signals(USER).signals] == ["travel"]


def test_only_closed_codes_can_be_stored_so_no_names_places_or_quotes_fit():
    agent = service()
    for kind, code in [
        (SignalKind.TOPIC, "Hà Nội"), (SignalKind.TOPIC, "my sister Lan"), (SignalKind.GOAL, "work at Acme"),
        (SignalKind.ERROR_TYPE, "He like football"), (SignalKind.ERROR_TYPE, "travel"),
        (SignalKind.PACE, "180 wpm"), (SignalKind.TOPIC, ""), (SignalKind.GOAL, "x" * 500),
    ]:
        assert agent.record(USER, language_code="en", kind=kind, code=code) is False
    assert agent.signals(USER).signals == []


def test_every_allowed_code_is_a_short_lowercase_identifier():
    for codes in ALLOWED_CODES.values():
        assert codes and all(code.isascii() and code.replace("_", "").isalpha() and code == code.lower()
                             and len(code) <= 32 for code in codes)


def test_nothing_is_recorded_without_consent():
    for granted in (None, False):
        agent = service(granted=granted)
        assert agent.record(USER, language_code="en", kind=SignalKind.TOPIC, code="travel") is False
        assert agent.signals(USER).signals == []


def test_recording_the_same_signal_again_counts_it_instead_of_adding_a_copy():
    agent = service()
    for _ in range(3):
        assert agent.record(USER, language_code="en", kind=SignalKind.ERROR_TYPE, code="verb_tense")
    [only] = agent.signals(USER).signals
    assert (only.kind, only.code, only.usage_count) == (SignalKind.ERROR_TYPE, "verb_tense", 3)


def test_fluency_keeps_one_current_value_per_language():
    agent = service()
    agent.record(USER, language_code="en", kind=SignalKind.PACE, code="slow")
    agent.record(USER, language_code="en", kind=SignalKind.PACE, code="steady")
    agent.record(USER, language_code="zh", kind=SignalKind.PACE, code="fast")
    assert sorted((item.language_code, item.code) for item in agent.signals(USER).signals) == [
        ("en", "steady"), ("zh", "fast")]


def test_the_learner_sees_only_their_own_signals_without_ids_of_other_learners():
    agent = service(signals=[signal(SignalKind.TOPIC, "food"), signal(SignalKind.TOPIC, "music", user=OTHER)])
    view = agent.signals(USER)
    assert [item.code for item in view.signals] == ["food"]
    assert "user_id" not in view.signals[0].model_dump()


def test_delete_one_and_delete_all_touch_only_the_owner():
    mine, theirs = signal(SignalKind.TOPIC, "food"), signal(SignalKind.TOPIC, "music", user=OTHER)
    agent = service(signals=[mine, theirs])
    assert agent.delete_one(OTHER, mine.id) is False
    assert agent.delete_one(USER, mine.id) is True
    agent.delete_all(USER)
    assert [row.id for row in agent.store.rows] == [theirs.id]


def test_migration_matches_the_domain_lists_and_is_owner_read_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    for kind, codes in ALLOWED_CODES.items():
        assert f"'{kind.value}'" in sql
        assert all(f"'{code}'" in sql for code in codes)
    assert "enable row level security" in sql
    assert "grant select on v3.learner_personalization_signals to authenticated" in sql
    assert "grant select on v3.learner_agent_consent to authenticated" in sql
    assert not re.search(r"grant\s+(insert|update|delete|all)[^;]*authenticated", sql)


@pytest.fixture
def api():
    agent = service(granted=None)
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_agent_signals_service] = lambda: agent
    try:
        yield SimpleNamespace(client=TestClient(app), agent=agent, headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_every_agent_route_needs_a_signed_in_learner(api):
    some = uuid4()
    calls = [api.client.get(f"{URL}/consent"), api.client.put(f"{URL}/consent", json={"granted": True}),
             api.client.get(f"{URL}/signals"), api.client.delete(f"{URL}/signals"),
             api.client.delete(f"{URL}/signals/{some}")]
    assert [call.status_code for call in calls] == [401] * 5


def test_consent_and_signals_through_the_api(api):
    assert api.client.get(f"{URL}/consent", headers=api.headers).json() == {"status": "ask", "decided_at": None}
    granted = api.client.put(f"{URL}/consent", json={"granted": True}, headers=api.headers).json()
    assert granted["status"] == "granted" and granted["decided_at"]
    api.agent.record(USER, language_code="en", kind=SignalKind.TOPIC, code="travel")
    body = api.client.get(f"{URL}/signals", headers=api.headers).json()
    assert [(row["kind"], row["code"], row["usage_count"]) for row in body["signals"]] == [("topic", "travel", 1)]
    row_id = body["signals"][0]["id"]
    assert api.client.delete(f"{URL}/signals/{row_id}", headers=api.headers).status_code == 204
    assert api.client.delete(f"{URL}/signals/{row_id}", headers=api.headers).status_code == 404
    api.agent.record(USER, language_code="en", kind=SignalKind.GOAL, code="travel")
    assert api.client.delete(f"{URL}/signals", headers=api.headers).status_code == 204
    assert api.client.get(f"{URL}/signals", headers=api.headers).json() == {"signals": []}


def test_consent_body_rejects_unknown_fields(api):
    response = api.client.put(f"{URL}/consent", json={"granted": True, "user_id": str(OTHER)}, headers=api.headers)
    assert response.status_code == 422


@pytest.mark.parametrize("kind,code,replace", [(SignalKind.TOPIC, "food", False), (SignalKind.PACE, "slow", True)])
def test_recording_a_signal_delegates_the_entire_write_to_one_rpc(kind, code, replace):
    from app.modules.learner.infrastructure.agent_signals import PersonalizationSignalRepository
    client = Mock()
    repository = PersonalizationSignalRepository(client)
    repository.record(USER, language_code="en", kind=kind, code=code, replace_kind=replace)
    client.schema.assert_called_once_with("v3")
    schema = client.schema.return_value
    schema.table.assert_not_called()
    schema.rpc.assert_called_once_with("record_personalization_signal", {
        "p_user_id": str(USER), "p_language_code": "en", "p_kind": kind.value,
        "p_code": code, "p_replace_kind": replace,
    })
    schema.rpc.return_value.execute.assert_called_once_with()
