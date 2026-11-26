"""Unhandled exceptions never reach callers, in any environment; details stay in server logs."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import api
from app.platform.logging import format_exception_safely


@pytest.mark.parametrize("environment", ["development", "test", "staging", "production"])
def test_unhandled_error_body_is_generic(monkeypatch, caplog, environment):
    monkeypatch.setattr(api.settings, "ENVIRONMENT", environment)
    application = api.create_app()

    @application.get("/boom")
    def boom():
        raise RuntimeError("relation v3.secret_table at /srv/internal/path failed")

    with caplog.at_level(logging.ERROR):
        response = TestClient(application, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": "InternalServerError", "message": "Lỗi hệ thống"}
    assert "secret_table" not in response.text and "/srv/internal" not in response.text
    # Builtin and app exception messages stay in the server-side traceback (SEC-07 keeps them).
    assert any(
        record.exc_info and "secret_table" in format_exception_safely(record.exc_info[1])
        for record in caplog.records
    )
