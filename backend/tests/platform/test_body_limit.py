"""SEC-02: oversized bodies are refused before a route parses them, with or without Content-Length."""
from __future__ import annotations

from fastapi import FastAPI, Form
from fastapi.testclient import TestClient

from app.main import app as deeplingo_app
from app.platform.body_limit import DEFAULT_MAX_BODY_BYTES, BodySizeLimitMiddleware

LIMIT = 1024


def _client() -> tuple[TestClient, list[int]]:
    parsed: list[int] = []
    application = FastAPI()
    application.add_middleware(BodySizeLimitMiddleware, max_body_bytes=LIMIT)

    @application.post("/form")
    def form(field: str = Form(...)):
        parsed.append(len(field))
        return {"ok": True}

    @application.post("/raw")
    async def raw(request_body: dict):
        return request_body

    return TestClient(application), parsed


def test_body_under_the_limit_reaches_the_route():
    client, parsed = _client()
    response = client.post("/form", data={"field": "x" * 100})
    assert response.status_code == 200
    assert parsed == [100]


def test_declared_oversized_body_is_refused_before_parsing():
    client, parsed = _client()
    response = client.post("/form", data={"field": "x" * (LIMIT * 4)})
    assert response.status_code == 413
    assert response.json()["error"] == "PayloadTooLarge"
    assert parsed == []


def test_streamed_body_without_content_length_is_counted():
    client, parsed = _client()

    def chunks():
        for _ in range(8):
            yield b"field=" + b"x" * LIMIT

    response = client.post(
        "/form",
        content=chunks(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    assert parsed == []


def test_oversized_json_body_is_refused():
    client, _ = _client()
    response = client.post("/raw", json={"text": "x" * (LIMIT * 4)})
    assert response.status_code == 413


def test_unauthenticated_oversized_upload_is_refused_without_parsing():
    client = TestClient(deeplingo_app)
    response = client.post(
        "/api/v1/v3/learner/me/speaking/shadowing/attempts",
        files={"audio": ("a.wav", b"\0" * (DEFAULT_MAX_BODY_BYTES + 1), "audio/wav")},
    )
    assert response.status_code == 413


def test_default_limit_still_admits_the_largest_speaking_upload():
    from app.modules.learning.api.speaking import MAX_UPLOAD_BYTES

    # Multipart framing adds well under 64 KiB to the audio part.
    assert MAX_UPLOAD_BYTES + 64 * 1024 <= DEFAULT_MAX_BODY_BYTES
