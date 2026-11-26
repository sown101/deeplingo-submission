"""Map typed integration failures into a narrow Content-only policy; no body scraping."""
import httpx
from openai import APIConnectionError, APIStatusError
from pydantic import ValidationError
from billiard.exceptions import SoftTimeLimitExceeded
from requests.exceptions import Timeout as RequestsTimeout, ConnectionError as RequestsConnectionError

from app.modules.content.domain.failures import ContentFailure, ContentFailureClass as C
from app.modules.content.application.ingestion import ContentIngestionError
from app.modules.content.application.ports import ContentProviderFailure
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory as P


def classify_content_failure(error: Exception) -> ContentFailure:
    chain, current = [], error
    while current is not None and id(current) not in {id(item) for item in chain}:
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    for item in reversed(chain):
        if isinstance(item, ContentProviderFailure):
            return ContentFailure(C.TRANSIENT if item.transient else C.PERMANENT, item.code, item.transient)
        if isinstance(item, (httpx.TimeoutException, TimeoutError, SoftTimeLimitExceeded, RequestsTimeout)):
            return ContentFailure(C.TRANSIENT, "transient_timeout", True)
        if isinstance(item, (httpx.TransportError, ConnectionError, APIConnectionError, RequestsConnectionError)):
            return ContentFailure(C.TRANSIENT, "transient_network", True)
        if isinstance(item, (APIStatusError, httpx.HTTPStatusError)):
            status = item.status_code if isinstance(item, APIStatusError) else item.response.status_code
            return _http_failure(status)
        if isinstance(item, LLMProviderError):
            if item.http_status is not None:
                return _http_failure(item.http_status)
            if item.category == P.TRANSPORT:
                # The old adapter also wraps unexpected bugs as TRANSPORT.
                return ContentFailure(C.UNKNOWN, "unknown_failure", True) if item.__cause__ else ContentFailure(C.TRANSIENT, "transient_network", True)
            if item.category in {P.CONFIGURATION, P.INCOMPATIBLE_RESPONSE}:
                return ContentFailure(C.PERMANENT, "configuration_error")
            return ContentFailure(C.PERMANENT, "validation_failed")
        if isinstance(item, ValidationError):
            return ContentFailure(C.PERMANENT, "validation_failed")
        # PostgREST safe SQLSTATE only: do not persist exception messages/details.
        code = str(getattr(item, "code", ""))
        if code in {"40001", "40P01", "53300", "57P01", "57014", "PGRST000", "PGRST001", "PGRST002", "PGRST003"} or code.startswith("08"):
            return ContentFailure(C.TRANSIENT, "database_temporary", True)
        if code in {"42501", "PGRST301", "PGRST302", "PGRST202"}:
            return ContentFailure(C.PERMANENT, "configuration_error")
        if code.startswith("23"):
            return ContentFailure(C.PERMANENT, "invariant_violation")
        if isinstance(item, ContentIngestionError) and not item.retryable:
            return ContentFailure(C.PERMANENT, "content_unavailable")
        if isinstance(item, ValueError) and not isinstance(item, ContentIngestionError):
            return ContentFailure(C.PERMANENT, "validation_failed")
    return ContentFailure(C.UNKNOWN, "unknown_failure", True)


def _http_failure(status: int) -> ContentFailure:
    if status == 429:
        return ContentFailure(C.TRANSIENT, "provider_rate_limit", True)
    if status in {408, 500, 502, 503, 504}:
        return ContentFailure(C.TRANSIENT, "provider_temporary", True)
    if status in {400, 401, 403, 422}:
        return ContentFailure(C.PERMANENT, "configuration_error")
    if status in {404, 410}:
        return ContentFailure(C.PERMANENT, "content_unavailable")
    return ContentFailure(C.UNKNOWN, "unknown_failure", True)
