import logging
import re
import sys
import traceback

# SEC-07: log records and exception chains can carry provider bodies, validation inputs or
# credentials (a `raise ... from exc` keeps the cause's text in the traceback). Every formatted
# record passes through redact() before it reaches a handler's output.
_SECRET_SETTINGS = (
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "AI_API_KEY",
    "GEMINI_API_KEY",
    "YOUTUBE_DATA_API_KEY",
    "AZURE_SPEECH_KEY",
    "SPEAKING_TICKET_SECRET",
)
_PATTERNS = (
    # pydantic ValidationError echoes the rejected input: "[type=..., input_value='...', input_type=str]"
    (re.compile(r"input_value=.*?(?=, input_type=)"), "input_value=<redacted>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer <redacted>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "<redacted-jwt>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "<redacted-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<redacted-key>"),
    (re.compile(r"(?i)([?&](?:key|api_key|access_token|token)=)[^&\s'\"]+"), r"\1<redacted>"),
)
MAX_LOG_LINE_CHARS = 2000


def _configured_secrets() -> list[str]:
    try:
        from app.platform.config import settings
    except Exception:
        return []
    values = (getattr(settings, name, "") or "" for name in _SECRET_SETTINGS)
    return sorted({value for value in values if len(value) >= 8}, key=len, reverse=True)


def redact(text: str) -> str:
    for secret in _configured_secrets():
        text = text.replace(secret, "<redacted-secret>")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    lines = text.split("\n")
    return "\n".join(
        line if len(line) <= MAX_LOG_LINE_CHARS
        else f"{line[:MAX_LOG_LINE_CHARS]}... <truncated {len(line) - MAX_LOG_LINE_CHARS} chars>"
        for line in lines
    )


_SAFE_EXCEPTION_ATTRS = ("status_code", "http_status", "code", "category")


def _message_is_ours(exc: BaseException) -> bool:
    module = type(exc).__module__
    return module == "builtins" or module == "app" or module.startswith("app.")


def _exception_line(exc: BaseException) -> str:
    cls = type(exc)
    name = cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"
    if _message_is_ours(exc):
        message = str(exc)
        return f"{name}: {message}" if message else name
    # Third-party messages can echo provider bodies, SQL rows or learner text: keep the type and
    # a few scalar diagnostics only.
    details = []
    for attr in _SAFE_EXCEPTION_ATTRS:
        value = getattr(exc, attr, None)
        value = getattr(value, "value", value)
        if isinstance(value, (int, str)) and not isinstance(value, bool) and len(str(value)) <= 64:
            details.append(f"{attr}={value}")
    return f"{name}: <message withheld{' ' + ' '.join(details) if details else ''}>"


def format_exception_safely(exc: BaseException) -> str:
    """Like traceback.format_exception, but only app and builtin exceptions keep their message."""
    chain: list[tuple[BaseException, str]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    link = ""
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append((current, link))
        if current.__cause__ is not None:
            current, link = current.__cause__, "\nThe above exception was the direct cause of the following exception:\n\n"
        elif current.__context__ is not None and not current.__suppress_context__:
            current, link = current.__context__, "\nDuring handling of the above exception, another exception occurred:\n\n"
        else:
            current = None
    parts: list[str] = []
    for index, (item, _) in enumerate(reversed(chain)):
        if index:
            parts.append(chain[len(chain) - index][1])
        if item.__traceback__ is not None:
            parts.append("Traceback (most recent call last):\n")
            parts.extend(traceback.format_tb(item.__traceback__))
        parts.append(_exception_line(item) + "\n")
    return "".join(parts).rstrip("\n")


class RedactingFormatter(logging.Formatter):
    def __init__(self, inner: logging.Formatter | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._inner = inner

    def format(self, record: logging.LogRecord) -> str:
        if record.exc_info and record.exc_info[1] is not None:
            # Formatter.format() reuses exc_text when set, so any wrapped formatter (Celery's too)
            # prints this safe rendering instead of the raw exception chain.
            record.exc_text = format_exception_safely(record.exc_info[1])
        formatted = self._inner.format(record) if self._inner else super().format(record)
        return redact(formatted)


def install_redaction(logger: logging.Logger | None = None) -> None:
    """Wrap the formatter of every handler on `logger` (root by default), e.g. Celery's."""
    for handler in (logger or logging.getLogger()).handlers:
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter or logging.Formatter()))


def setup_logging():
    """Cấu hình logging hỗ trợ tiếng Việt"""
    
    # Format
    formatter = RedactingFormatter(
        None,
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console Handler với UTF-8 encoding
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # ⭐ FIX: Force UTF-8 encoding
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    
    # Root Logger
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)
    
    return root_logger
