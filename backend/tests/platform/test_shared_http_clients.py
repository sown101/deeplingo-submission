"""One httpx connection pool per process for the ADC provider and the Openverse image search."""
import httpx

from app.bootstrap.wiring import content as content_wiring
from app.platform.llm import openai_compatible


def test_the_adc_provider_shares_one_client_per_timeout(monkeypatch) -> None:
    monkeypatch.setattr(openai_compatible, "_adc_http_clients", {})
    monkeypatch.setattr(openai_compatible, "_application_default_auth", lambda: httpx.BasicAuth("u", "p"))
    first = openai_compatible._application_default_http_client(30.0)
    assert openai_compatible._application_default_http_client(30.0) is first
    assert openai_compatible._application_default_http_client(5.0) is not first
    first.close()
    openai_compatible._adc_http_clients[5.0].close()


def test_the_openverse_client_is_one_per_process() -> None:
    assert content_wiring._openverse_http_client() is content_wiring._openverse_http_client()
    assert content_wiring._openverse_http_client().timeout == httpx.Timeout(8.0)
