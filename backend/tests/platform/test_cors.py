"""Focused CORS boundary tests for the Web browser deployment.

Proves, without exercising the wider backend architecture:

- an explicitly configured production origin is accepted;
- an unconfigured origin is rejected (no reflected/wildcard origin);
- the local development default keeps the Vite dev server workflow working;
- Authorization is an allowed preflight header (Bearer remains the
  authentication authority; no cookie/credentials CORS is enabled);
- wildcard origins are never produced by default or by explicit configuration;
- every method the Web client sends (including PATCH/DELETE for Companion
  memory and saved words) passes preflight from a configured origin (SEC-05).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.bootstrap.api import cors_middleware_kwargs


def _app_for(origin_setting: str) -> TestClient:
    application = FastAPI()
    application.add_middleware(CORSMiddleware, **cors_middleware_kwargs(origin_setting))

    @application.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(application)


PREFLIGHT = {
    "Origin": "https://app.example.com",
    "Access-Control-Request-Method": "GET",
}


def test_configured_production_origin_is_accepted():
    client = _app_for("https://app.example.com")
    response = client.options("/ping", headers=PREFLIGHT)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "access-control-allow-credentials" not in response.headers


def test_unconfigured_origin_is_rejected():
    client = _app_for("https://app.example.com")
    response = client.options(
        "/ping",
        headers={**PREFLIGHT, "Origin": "https://evil.example"},
    )
    assert response.status_code in {400, 403}
    assert "access-control-allow-origin" not in response.headers


def test_local_development_default_keeps_vite_dev_server_working():
    client = _app_for("")
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options("/ping", headers={**PREFLIGHT, "Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_authorization_is_an_allowed_preflight_header():
    client = _app_for("https://app.example.com")
    response = client.options(
        "/ping",
        headers={
            **PREFLIGHT,
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"]
    assert "authorization" in allowed.casefold()
    assert "content-type" in allowed.casefold()


def test_no_wildcard_origins_are_ever_produced():
    for origin_setting in (
        "",
        "https://app.example.com",
        "https://a.example.com,https://b.example.com",
    ):
        client = _app_for(origin_setting)
        response = client.options("/ping", headers=PREFLIGHT)
        allowed = response.headers.get("access-control-allow-origin")
        assert allowed != "*"


def test_explicit_multiple_origins_are_all_accepted():
    client = _app_for("https://app.example.com,https://web.example.org")
    for origin in ("https://app.example.com", "https://web.example.org"):
        response = client.options("/ping", headers={**PREFLIGHT, "Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("method", ["GET"])
def test_simple_get_from_configured_origin_is_allowed(method):
    client = _app_for("https://app.example.com")
    response = client.get("/ping", headers={"Origin": "https://app.example.com"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_web_client_methods_pass_preflight_from_configured_origin(method):
    client = _app_for("https://app.example.com")
    response = client.options(
        "/ping",
        headers={**PREFLIGHT, "Access-Control-Request-Method": method},
    )
    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


def test_delete_preflight_from_unconfigured_origin_is_still_rejected():
    client = _app_for("https://app.example.com")
    response = client.options(
        "/ping",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert response.status_code in {400, 403}
    assert "access-control-allow-origin" not in response.headers
