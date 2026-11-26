"""SEC-07: exception chains and messages are redacted before they reach log output."""
from __future__ import annotations

import io
import logging

import pytest
from pydantic import BaseModel, ValidationError

import httpx
import openai

from app.platform import logging as platform_logging
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory
from app.platform.logging import (
    MAX_LOG_LINE_CHARS,
    RedactingFormatter,
    format_exception_safely,
    install_redaction,
    redact,
)

SENTINEL = "learner-answer-sentinel-7f3a"
FAKE_GOOGLE_KEY = "AIza" + "A" * 35
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"


class _Strict(BaseModel):
    score: int


class ProviderError(Exception):
    pass


def _capture(logger_name: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(None, "%(levelname)s %(message)s"))
    logger = logging.getLogger(logger_name)
    logger.handlers = [handler]
    logger.propagate = False
    return logger, stream


def test_validation_input_in_a_chained_cause_is_redacted():
    logger, stream = _capture("sec07.validation")
    try:
        try:
            _Strict.model_validate({"score": SENTINEL})
        except ValidationError as exc:
            raise ProviderError("structured output rejected") from exc
    except ProviderError:
        logger.exception("assessment failed")

    output = stream.getvalue()
    assert SENTINEL not in output
    assert "pydantic_core._pydantic_core.ValidationError: <message withheld>" in output
    assert "Traceback" in output and "structured output rejected" in output


def test_input_value_pattern_is_still_masked_in_free_text():
    assert SENTINEL not in redact(f"[type=int_parsing, input_value='{SENTINEL}', input_type=str]")


def test_credentials_in_messages_and_provider_bodies_are_redacted():
    logger, stream = _capture("sec07.credentials")
    body = f'{{"error": "bad", "url": "https://x.test/v1?key={FAKE_GOOGLE_KEY}"}}'
    try:
        raise ProviderError(body)
    except ProviderError:
        logger.exception("call failed with Authorization: Bearer %s", FAKE_JWT)

    output = stream.getvalue()
    assert FAKE_GOOGLE_KEY not in output
    assert FAKE_JWT not in output
    assert "Bearer <redacted>" in output


def test_configured_secret_values_are_redacted(monkeypatch):
    monkeypatch.setattr(platform_logging, "_configured_secrets", lambda: ["service-role-value-123"])
    assert "service-role-value-123" not in redact("token=service-role-value-123 rejected")


def test_huge_single_line_bodies_are_truncated():
    line = "x" * (MAX_LOG_LINE_CHARS * 3)
    redacted = redact(line)
    assert len(redacted) < MAX_LOG_LINE_CHARS + 100
    assert "truncated" in redacted


def test_install_redaction_wraps_foreign_handlers_once():
    logger = logging.getLogger("sec07.celery")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.propagate = False

    install_redaction(logger)
    install_redaction(logger)
    logger.error("token %s", FAKE_JWT)

    assert isinstance(handler.formatter, RedactingFormatter)
    assert not isinstance(handler.formatter._inner, RedactingFormatter)
    assert FAKE_JWT not in stream.getvalue()


@pytest.mark.parametrize("text", ["HTTP end GET /health -> 200 in 3.1ms", "Verifying Supabase JWT with mode=jwks"])
def test_ordinary_lines_pass_through_unchanged(text):
    assert redact(text) == text


LEARNER_TEXT = "PRIVATE_LEARNER_RESPONSE_RECHECK my answer is the cat sleeps"


def _provider_failure() -> LLMProviderError:
    body = {"error": {"message": f"Invalid input near: {LEARNER_TEXT}", "code": "invalid_request"}}
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://provider.test/v1/chat/completions"),
        json=body,
    )
    try:
        try:
            raise openai.BadRequestError(f"Error code: 400 - {body}", response=response, body=body)
        except openai.APIStatusError as exc:
            raise LLMProviderError(
                "Structured generation provider failed",
                category=LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE,
                http_status=exc.status_code,
            ) from exc
    except LLMProviderError as error:
        return error


def test_sdk_error_body_with_ordinary_learner_text_never_reaches_the_log():
    """Recheck finding: plain learner text has no credential shape, so regexes cannot catch it."""
    logger, stream = _capture("sec07.sdk")
    error = _provider_failure()
    logger.error("assessment provider failed", exc_info=error)

    output = stream.getvalue()
    assert "PRIVATE_LEARNER_RESPONSE_RECHECK" not in output
    assert "cat sleeps" not in output
    assert "openai.BadRequestError: <message withheld status_code=400>" in output
    assert "LLMProviderError: Structured generation provider failed" in output
    assert "direct cause of the following exception" in output
    assert output.index("openai.BadRequestError") < output.index("LLMProviderError")


def test_sdk_error_body_is_withheld_behind_a_wrapped_celery_style_formatter():
    logger = logging.getLogger("sec07.sdk.celery")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.handlers = [handler]
    logger.propagate = False
    install_redaction(logger)

    logger.error("task failed", exc_info=_provider_failure())

    assert "PRIVATE_LEARNER_RESPONSE_RECHECK" not in stream.getvalue()
    assert "<message withheld" in stream.getvalue()


def test_app_and_builtin_exception_messages_are_kept():
    try:
        try:
            {}["expected_key"]
        except KeyError as exc:
            raise LLMProviderError("Provider returned no parsed structured result") from exc
    except LLMProviderError as error:
        rendered = format_exception_safely(error)
    assert "KeyError: 'expected_key'" in rendered
    assert "Provider returned no parsed structured result" in rendered


def test_unhandled_error_logs_type_without_message(caplog):
    from fastapi.testclient import TestClient
    from app.main import app

    @app.get("/__sec07_boom")
    def boom():
        raise openai.BadRequestError(
            LEARNER_TEXT,
            response=httpx.Response(400, request=httpx.Request("POST", "https://provider.test")),
            body=None,
        )

    try:
        with caplog.at_level(logging.ERROR, logger="app.bootstrap.api"):
            response = TestClient(app, raise_server_exceptions=False).get("/__sec07_boom")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__sec07_boom"]

    assert response.status_code == 500
    records = [r for r in caplog.records if r.name == "app.bootstrap.api" and "Unhandled error" in r.getMessage()]
    assert records and records[-1].getMessage() == "Unhandled error BadRequestError"
    assert LEARNER_TEXT not in RedactingFormatter(None, "%(message)s").format(records[-1])
