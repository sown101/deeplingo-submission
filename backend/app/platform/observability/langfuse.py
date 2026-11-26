"""Best-effort Langfuse adapter for text turns."""
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Literal
from uuid import uuid4

from opentelemetry import context

from app.platform.observability.port import Observation, Turn

logger = logging.getLogger(__name__)

_CREDENTIAL = re.compile(
    r"""(?ix)\b(?:bearer|basic|token)[ \t]+[\w./+=~-]+"""
    r"""|\b(?:[\w-]*token|api[_ -]?key|secret|password|authorization)["']?\s*[:=]\s*"""
    r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[\w./+=~-]+)"""
)
_EMAIL = re.compile(r"(?i)[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)*")
_PHONE = re.compile(r"(?i)(?<!\w)\(?\+?\d[\d() .-]{5,}\d(?:\s*(?:ext\.?|x|#)\s*\d{1,6})?(?!\w)")
_TOKEN = re.compile(
    r"(?i)\b(?:sk[-_]|pk[-_]|gh[pousr]_|github_pat_|xox[baprs]-|AIza)[\w-]+"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|(?<![\w-])[A-Za-z0-9_+/-]{24,}={0,2}(?![\w-])"
)
_INLINE_MEDIA = re.compile(r"(?i)data:[\w.+/-]+;base64,[\w+/=]+")


def redact(text: str) -> str:
    text = _INLINE_MEDIA.sub("[redacted]", text)
    text = _CREDENTIAL.sub("[redacted]", text)
    text = _EMAIL.sub("[redacted]", text)
    text = _PHONE.sub(lambda match: "[redacted]" if sum(c.isdigit() for c in match[0]) >= 7 else match[0], text)
    return _TOKEN.sub("[redacted]", text)


def _safe_sdk_log(record: logging.LogRecord) -> bool | logging.LogRecord:
    if record.levelno < logging.WARNING:
        return False
    # Export failures can include a response body or exception. Keep only a fixed warning.
    return logging.LogRecord(__name__, logging.WARNING, __file__, 0, "Langfuse SDK warning", (), None)


def create_client(*, host: str, public_key: str, secret_key: str):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider

    for name in ("langfuse", "opentelemetry.exporter.otlp.proto.http.trace_exporter",
                 "opentelemetry.exporter.otlp.proto.http._common",
                 "opentelemetry.exporter.otlp.common.http", "opentelemetry.sdk._shared_internal"):
        logging.getLogger(name).addFilter(_safe_sdk_log)
    return Langfuse(base_url=host, public_key=public_key, secret_key=secret_key,
                    debug=False, tracer_provider=TracerProvider())


def _sdk_call(operation, **fields):
    # SDK calls must never inherit another tracer's spans or baggage.
    token = context.attach(context.Context())
    try:
        return operation(**fields)
    except Exception:
        logger.warning("Langfuse observation failed")
        return None
    finally:
        context.detach(token)


@contextmanager
def _observe(start, *, capture_content: bool, metadata: dict | None = None,
             **fields) -> Iterator[tuple]:
    started = perf_counter()
    span = _sdk_call(start, **fields)
    if span is None:
        yield None, None
        return
    observation = Observation(capture_content)
    try:
        yield span, observation
    except BaseException:
        observation.status = "error"
        raise
    finally:
        attributes = {**(metadata or {}), "status": observation.status,
                      "latency_ms": round((perf_counter() - started) * 1000, 3)}
        if observation.failure_category:
            attributes["failure_category"] = observation.failure_category
        updates = {"metadata": attributes}
        if observation.status == "error":
            updates["level"] = "ERROR"
        if observation.usage is not None:
            updates["usage_details"] = observation.usage
            if observation.estimated_cost_usd is not None:
                updates["cost_details"] = {"total": observation.estimated_cost_usd}
        try:
            # Legal gate before launch: only this opt-in can export redacted text.
            if capture_content:
                if isinstance(observation.input, list):
                    updates["input"] = [redact(value) for value in observation.input]
                elif observation.input is not None:
                    updates["input"] = redact(observation.input)
                if observation.output is not None:
                    updates["output"] = redact(observation.output)
            _sdk_call(span.update, **updates)
        except Exception:
            logger.warning("Langfuse observation could not be prepared")
        finally:
            _sdk_call(span.end)


class _LangfuseTurn:
    def __init__(self, root, capture_content: bool):
        self._root = root
        self._capture_content = capture_content
        self.tool_rounds = 0
        self.closed = False

    @contextmanager
    def span(self, kind: Literal["generation", "tool"], name: str, *,
             model: str | None = None) -> Iterator[Observation | None]:
        if self.closed:
            yield None
            return
        fields = {"model": model} if model is not None else {}
        with _observe(self._root.start_observation, capture_content=self._capture_content,
                      name=name, as_type=kind, **fields) as (_, observation):
            yield observation


class LangfuseTracing:
    def __init__(self, client, *, capture_content: bool):
        self._client = client
        self._capture_content = capture_content

    @contextmanager
    def turn(self, phase: Literal["start", "turn"]) -> Iterator[Turn | None]:
        # Each execution gets an unrelated random ID, including retries of the same learner turn.
        metadata = {"phase": phase, "tool_rounds": 0}
        with _observe(self._client.start_observation, capture_content=False, metadata=metadata,
                      name="text-agent-turn", as_type="agent", trace_context={"trace_id": uuid4().hex}) as (root, _):
            if root is None:
                yield None
                return
            turn = _LangfuseTurn(root, self._capture_content)
            try:
                yield turn
            finally:
                turn.closed = True
                metadata["tool_rounds"] = turn.tool_rounds
