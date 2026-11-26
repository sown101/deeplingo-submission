"""Web Product V1 runtime E2E helpers.

Creates/removes a DISPOSABLE Supabase Auth learner for the Web E2E run.
Guarded by the same rules as existing backend smokes: development
environment, ALLOW_TEST_SEEDING=true, and an exact expected Supabase
project ref. No Concept/LearningObject/ReviewState/mastery fixture is ever
created; the learner's product state comes only from real APIs.

State (credentials) lives in the OS temp directory; only a path is printed.

The helper is working-directory independent: repository paths derive from
this file, and backend/.env is loaded explicitly (never overriding real
environment variables, so CI secrets win) before backend settings import.

Usage (any working directory; Python needs the backend requirements):
  python deeplingo_web/scripts/e2e_learner.py setup
  python deeplingo_web/scripts/e2e_learner.py cleanup <state_path>
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# Explicit, non-overriding load so cleanup/setup behave identically from any
# caller working directory while CI/exported environment variables keep
# priority.
load_dotenv(BACKEND / ".env", override=False)
for candidate in (ROOT, BACKEND):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.platform.config import settings  # noqa: E402


def _guard() -> None:
    if settings.ENVIRONMENT != "development":
        raise RuntimeError("Web E2E requires ENVIRONMENT=development")
    if os.getenv("ALLOW_TEST_SEEDING", "").strip().casefold() != "true":
        raise RuntimeError("Set ALLOW_TEST_SEEDING=true")
    project_ref = (urlparse(settings.SUPABASE_URL).hostname or "").split(".")[0]
    expected = os.getenv("SMOKE_EXPECTED_SUPABASE_PROJECT_REF", "").strip()
    if not expected or not secrets.compare_digest(project_ref, expected):
        raise RuntimeError("Configured Supabase project does not match the expected smoke target")
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase service role key is unavailable")


def _headers() -> dict[str, str]:
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def setup() -> None:
    _guard()
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    email = f"devweb{suffix}@example.invalid"
    password = secrets.token_hex(16)
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users",
            headers=_headers(),
            json={
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"display_name": f"DEV_E2E_WEB_{suffix}"},
            },
        )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"Temporary Auth user creation failed ({response.status_code})")
    state = {
        "run": "WEB_PRODUCT_V1_E2E",
        "user_id": response.json()["id"],
        "email": email,
        "password": password,
    }
    path = Path(tempfile.gettempdir()) / f"deeplingo-web-e2e-{suffix}.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    print(json.dumps({"status": "created", "state_path": str(path)}), flush=True)


def cleanup(state_path: str) -> None:
    _guard()
    path = Path(state_path).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if path.parent != temp_root or not path.name.startswith("deeplingo-web-e2e-"):
        raise RuntimeError("State must be a deeplingo-web-e2e-*.json file in OS temp")
    state = json.loads(path.read_text(encoding="utf-8"))
    user_id = state["user_id"]
    _remove_learner_rows(user_id)
    with httpx.Client(timeout=30) as client:
        response = client.delete(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}",
            headers=_headers(),
        )
    if response.status_code not in {200, 204, 404}:
        raise RuntimeError(f"Temporary Auth user removal failed ({response.status_code})")
    path.unlink(missing_ok=True)
    print(json.dumps({"status": "clean", "user_removed": True}), flush=True)


def _remove_learner_rows(user_id: str) -> None:
    """Removes ONLY this disposable learner's rows; shared global content
    (videos, concepts, learning objects) is retained."""
    from app.platform.supabase import supabase_service  # noqa: E402

    if supabase_service is None:
        raise RuntimeError("Supabase service client is unavailable")

    def table(name):
        return supabase_service.schema("v3").table(name)

    def owned(name):
        return table(name).select("*").eq("user_id", user_id).execute().data or []

    review_ids = [row["id"] for row in owned("review_states")]
    group_ids = [row["id"] for row in owned("word_groups")]
    for review_id in review_ids:
        table("review_events").delete().eq("review_state_id", review_id).execute()
    for group_id in group_ids:
        table("word_group_items").delete().eq("group_id", group_id).execute()
    for name in (
        "word_groups",
        "learner_activity_log",
        "learner_agent_memory",
        "review_states",
        "saved_concepts",
        "learner_videos",
        "user_language_preferences",
    ):
        table(name).delete().eq("user_id", user_id).execute()
    table("profiles").delete().eq("id", user_id).execute()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: e2e_learner.py setup | cleanup <state_path>")
    if sys.argv[1] == "setup":
        setup()
    elif sys.argv[1] == "cleanup":
        if len(sys.argv) != 3:
            raise SystemExit("cleanup requires a state path")
        cleanup(sys.argv[2])
    else:
        raise SystemExit("unknown command")
