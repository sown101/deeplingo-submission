"""FR-6.1: the learner deletes their own account in one confirmed request.

Everything that belongs to them goes with the account (their rows cascade from the sign-in user); shared
content (videos, transcripts, dictionaries) is never touched. Tests use a fake sign-in admin."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_account_deletion_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.account_deletion import (
    CONFIRMATION,
    AccountDeletionError,
    AccountDeletionService,
)

USER, OTHER = uuid4(), uuid4()
URL = "/api/v1/v3/learner/me/account/delete"


class FakeAdmin:
    def __init__(self, fail=False):
        self.deleted, self.fail = [], fail

    def delete_user(self, user_id):
        if self.fail:
            raise RuntimeError("provider down")
        self.deleted.append(user_id)


def test_only_the_exact_confirmation_deletes_the_account():
    admin = FakeAdmin()
    service = AccountDeletionService(users=admin)
    for wrong in ("", "delete", "DELETE ", "yes", None):
        with pytest.raises(AccountDeletionError) as raised:
            service.delete(USER, wrong)
        assert raised.value.code == "account_deletion_not_confirmed" and raised.value.status_code == 422
    assert admin.deleted == []
    service.delete(USER, CONFIRMATION)
    assert admin.deleted == [USER]


def test_a_failure_is_reported_never_claimed_as_done():
    service = AccountDeletionService(users=FakeAdmin(fail=True))
    with pytest.raises(AccountDeletionError) as raised:
        service.delete(USER, CONFIRMATION)
    assert raised.value.status_code == 503 and raised.value.code == "account_deletion_unavailable"
    assert "provider" not in str(raised.value)


@pytest.fixture
def api():
    admin = FakeAdmin()
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_account_deletion_service] = lambda: AccountDeletionService(users=admin)
    try:
        yield SimpleNamespace(client=TestClient(app), admin=admin, headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_the_route_needs_a_signed_in_learner(api):
    assert api.client.post(URL, json={"confirm": CONFIRMATION}).status_code == 401
    assert api.admin.deleted == []


def test_the_route_deletes_only_the_signed_in_learner_and_ignores_any_other_id(api):
    response = api.client.post(URL, json={"confirm": CONFIRMATION}, headers=api.headers)
    assert response.status_code == 204 and api.admin.deleted == [USER]
    forged = api.client.post(URL, json={"confirm": CONFIRMATION, "user_id": str(OTHER)}, headers=api.headers)
    assert forged.status_code == 422 and api.admin.deleted == [USER]


def test_a_missing_or_wrong_confirmation_is_refused_with_nothing_deleted(api):
    assert api.client.post(URL, json={}, headers=api.headers).status_code == 422
    wrong = api.client.post(URL, json={"confirm": "no"}, headers=api.headers)
    assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "account_deletion_not_confirmed"
    assert api.admin.deleted == []


def test_the_response_is_never_cached(api):
    response = api.client.post(URL, json={"confirm": CONFIRMATION}, headers=api.headers)
    assert response.headers.get("cache-control") == "no-store"
