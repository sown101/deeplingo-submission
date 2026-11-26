"""Bounded development-only smoke for Supabase RLS and authority boundaries.

Run from the backend repository root with both guards set::

    ALLOW_TEST_SEEDING=true
    SMOKE_EXPECTED_SUPABASE_PROJECT_REF=<development-project-ref>

The smoke creates two temporary Auth users, exercises the real hosted Data API
and FastAPI service path, and removes all fixtures in a finally block. It never
prints credentials, JWTs, email addresses, or persistent identifiers.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.platform.config import settings
from app.platform.supabase import supabase_service
from app.main import app  # noqa: E402


API_PREFIX = f"{settings.API_V1_STR}/v3"


def _guard() -> str:
    environment = (settings.ENVIRONMENT or "").strip().casefold()
    if environment == "production":
        raise RuntimeError("Refusing security smoke in production")
    if environment not in {"development", "dev", "local", "staging"}:
        raise RuntimeError("Security smoke requires an explicit non-production environment")
    if os.getenv("ALLOW_TEST_SEEDING", "").strip().casefold() != "true":
        raise RuntimeError("Set ALLOW_TEST_SEEDING=true to authorize development fixtures")
    hostname = urlparse(settings.SUPABASE_URL).hostname or ""
    project_ref = hostname.split(".")[0]
    expected_ref = os.getenv("SMOKE_EXPECTED_SUPABASE_PROJECT_REF", "").strip()
    if not expected_ref or not secrets.compare_digest(project_ref, expected_ref):
        raise RuntimeError("Configured Supabase project does not match the explicit smoke target")
    if supabase_service is None:
        raise RuntimeError("Supabase service client is not configured")
    if not settings.SUPABASE_KEY or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase anon and service-role credentials are required")
    return project_ref


def _headers(key: str, token: str | None = None, *, profile: str | None = None) -> dict[str, str]:
    headers = {"apikey": key, "Authorization": f"Bearer {token or key}"}
    if profile:
        headers["Accept-Profile"] = profile
        headers["Content-Profile"] = profile
    return headers


def _create_auth_user(client: httpx.Client, suffix: str) -> tuple[UUID, str, str]:
    email = f"deeplingo.security.smoke.{suffix}@example.invalid"
    password = secrets.token_urlsafe(30)
    response = client.post(
        f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users",
        headers=_headers(settings.SUPABASE_SERVICE_ROLE_KEY),
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"display_name": "DEV_SECURITY_SMOKE"},
        },
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"Development auth-user creation failed ({response.status_code})")
    return UUID(response.json()["id"]), email, password


def _sign_in(client: httpx.Client, email: str, password: str) -> str:
    response = client.post(
        f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password",
        headers={"apikey": settings.SUPABASE_KEY},
        json={"email": email, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError(f"Development smoke sign-in failed ({response.status_code})")
    return response.json()["access_token"]


def _delete_auth_user(client: httpx.Client, user_id: UUID) -> None:
    response = client.delete(
        f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}",
        headers=_headers(settings.SUPABASE_SERVICE_ROLE_KEY),
    )
    if response.status_code not in {200, 204, 404}:
        raise RuntimeError(f"Development auth-user cleanup failed ({response.status_code})")


def _expect_ok(response: Any) -> Any:
    if response.status_code != 200:
        raise RuntimeError(f"Expected success, received HTTP {response.status_code}")
    return response.json()


def _expect_denied(response: httpx.Response, label: str) -> int:
    if response.status_code < 400:
        raise RuntimeError(f"{label} unexpectedly succeeded")
    return response.status_code


def _cleanup(client: httpx.Client, user_ids: list[UUID]) -> dict[str, Any]:
    errors: list[str] = []
    for user_id in user_ids:
        for table in ("user_language_preferences",):
            try:
                supabase_service.schema("v3").table(table).delete().eq("user_id", str(user_id)).execute()
            except Exception as exc:  # cleanup must continue
                errors.append(type(exc).__name__)
        try:
            supabase_service.schema("v3").table("profiles").delete().eq("id", str(user_id)).execute()
        except Exception as exc:
            errors.append(type(exc).__name__)
        try:
            _delete_auth_user(client, user_id)
        except Exception as exc:
            errors.append(type(exc).__name__)
    return {"completed": not errors, "error_types": errors, "users_removed": len(user_ids)}


def main() -> int:
    project_ref = _guard()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    users: list[UUID] = []
    result: dict[str, Any] = {
        "status": "failed",
        "environment": settings.ENVIRONMENT,
        "project_match": bool(project_ref),
    }

    with httpx.Client(timeout=30) as client:
        try:
            credentials = []
            for label in ("a", "b"):
                user_id, email, password = _create_auth_user(client, f"{suffix}.{label}")
                users.append(user_id)
                credentials.append((user_id, _sign_in(client, email, password)))

            user_a, token_a = credentials[0]
            user_b, token_b = credentials[1]
            auth_a = {"Authorization": f"Bearer {token_a}"}
            auth_b = {"Authorization": f"Bearer {token_b}"}

            with TestClient(app) as api:
                for headers in (auth_a, auth_b):
                    initialized = _expect_ok(
                        api.post(
                            f"{API_PREFIX}/learner/me/initialize",
                            headers=headers,
                            json={"language_codes": ["en"], "create_profile": True},
                        )
                    )
                    if initialized.get("profile_status") not in {"created", "existing"}:
                        raise RuntimeError("FastAPI initialization did not establish a profile")

                language_profile = _expect_ok(
                    api.put(
                        f"{API_PREFIX}/learner/me/language-profile",
                        headers=auth_a,
                        json={"learning_language": "en", "support_language": "vi"},
                    )
                )
                if language_profile.get("support_language") != "vi":
                    raise RuntimeError("Authorized language-profile write did not persist")

            rest_headers_a = _headers(settings.SUPABASE_KEY, token_a, profile="v3")
            rest_root = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1"

            own_profile = client.get(
                f"{rest_root}/profiles",
                headers=rest_headers_a,
                params={"select": "id", "id": f"eq.{user_a}"},
            )
            cross_profile = client.get(
                f"{rest_root}/profiles",
                headers=rest_headers_a,
                params={"select": "id", "id": f"eq.{user_b}"},
            )
            own_preferences = client.get(
                f"{rest_root}/user_language_preferences",
                headers=rest_headers_a,
                params={"select": "user_id,language_code", "user_id": f"eq.{user_a}"},
            )
            cross_preferences = client.get(
                f"{rest_root}/user_language_preferences",
                headers=rest_headers_a,
                params={"select": "user_id,language_code", "user_id": f"eq.{user_b}"},
            )
            if own_profile.status_code != 200 or len(own_profile.json()) != 1:
                raise RuntimeError("Own-row profile read failed")
            if cross_profile.status_code != 200 or cross_profile.json() != []:
                raise RuntimeError("Cross-user profile read was not denied by RLS")
            if own_preferences.status_code != 200 or not own_preferences.json():
                raise RuntimeError("Own-row language-preference read failed")
            if cross_preferences.status_code != 200 or cross_preferences.json() != []:
                raise RuntimeError("Cross-user language-preference read was not denied by RLS")

            preference_write = client.patch(
                f"{rest_root}/user_language_preferences",
                headers={**rest_headers_a, "Prefer": "return=representation"},
                params={"user_id": f"eq.{user_a}"},
                json={"support_language_code": "en"},
            )
            progress_write = client.post(
                f"{rest_root}/learner_grammar_progress",
                headers={**rest_headers_a, "Prefer": "return=representation"},
                json={"user_id": str(user_a)},
            )
            critical_rpc = client.post(
                f"{rest_root}/rpc/record_grammar_answer",
                headers=rest_headers_a,
                json={
                    "p_user_id": str(user_a),
                    "p_language_code": "en",
                    "p_grammar_key": "smoke",
                    "p_answer": {},
                },
            )

            anon_headers = _headers(settings.SUPABASE_KEY, profile="v3")
            public_content = client.get(
                f"{rest_root}/languages",
                headers=anon_headers,
                params={"select": "code", "limit": "1"},
            )
            anon_authority = client.get(
                f"{rest_root}/user_language_preferences",
                headers=anon_headers,
                params={"select": "user_id", "limit": "1"},
            )
            if public_content.status_code != 200:
                raise RuntimeError("Intended anonymous V3 content read failed")

            result.update(
                {
                    "status": "passed",
                    "cross_user": {
                        "profile_hidden": True,
                        "language_preference_hidden": True,
                    },
                    "own_row_reads": {
                        "profile": True,
                        "language_preference": True,
                    },
                    "direct_authority_writes": {
                        "language_profile_http": _expect_denied(preference_write, "language-profile write"),
                        "grammar_progress_http": _expect_denied(progress_write, "grammar progress write"),
                        "critical_rpc_http": _expect_denied(critical_rpc, "critical RPC invocation"),
                    },
                    "service_authority": {
                        "initialization": True,
                        "language_profile_write": True,
                    },
                    "content_visibility": {
                        "anon_public_content": True,
                        "anon_authority_http": _expect_denied(anon_authority, "anonymous authority read"),
                    },
                }
            )
            return_code = 0
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)
            return_code = 1
        finally:
            result["cleanup"] = _cleanup(client, users)
            if not result["cleanup"]["completed"]:
                result["status"] = "failed"
                return_code = 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
