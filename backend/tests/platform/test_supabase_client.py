"""The process Supabase client must not share an HTTP/2 connection across threads.

Shared sync HTTP/2 failed concurrent reads with EAGAIN ("[Errno 11]" / WinError 10035);
PostgREST is therefore routed through an explicit HTTP/1.1 httpx pool.
"""
import httpx

from app.platform import supabase as platform_supabase

URL = "https://example-project.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature"


def build(monkeypatch, created):
    def tracked():
        client = httpx.Client(http2=False, timeout=platform_supabase.SUPABASE_HTTP_TIMEOUT_SECONDS)
        created.append(client)
        return client

    monkeypatch.setattr(platform_supabase.settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(platform_supabase.settings, "SUPABASE_SERVICE_ROLE_KEY", KEY)
    monkeypatch.setattr(platform_supabase, "_http1_client", tracked)
    return platform_supabase._build_client(service=True)


def test_postgrest_uses_the_injected_http1_client(monkeypatch):
    created = []
    client = build(monkeypatch, created)

    assert len(created) == 1
    assert client.postgrest.session is created[0]
    assert client.options.httpx_client is created[0]


def test_schema_clients_are_cached_and_share_the_pool(monkeypatch):
    created = []
    client = build(monkeypatch, created)

    v3 = client.schema("v3")
    assert client.schema("v3") is v3
    assert v3.session is created[0]
    assert v3.headers["accept-profile"] == "v3" and v3.headers["content-profile"] == "v3"
    assert v3.headers["apikey"] == KEY and v3.headers["authorization"] == f"Bearer {KEY}"
    assert client.schema("public") is not v3 and client.schema("public").session is created[0]


def test_default_http_client_disables_http2():
    client = platform_supabase._http1_client()
    try:
        assert client._transport._pool._http2 is False
        assert client._transport._pool._http1 is True
        assert client.timeout.read == platform_supabase.SUPABASE_HTTP_TIMEOUT_SECONDS
    finally:
        client.close()


def test_close_client_closes_the_injected_pool(monkeypatch):
    created = []
    client = build(monkeypatch, created)
    client.postgrest  # materialize the lazily created PostgREST sub-client
    platform_supabase._close_client(client)
    assert created[0].is_closed


def test_unqualified_rpc_targets_the_v3_schema(monkeypatch):
    # Repositories call client.rpc(...) without .schema(); every backend RPC lives in v3.
    seen = []

    def mock_http1():
        return httpx.Client(http2=False, transport=httpx.MockTransport(
            lambda request: seen.append(request) or httpx.Response(200, json={"created": False})))

    monkeypatch.setattr(platform_supabase.settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(platform_supabase.settings, "SUPABASE_SERVICE_ROLE_KEY", KEY)
    monkeypatch.setattr(platform_supabase, "_http1_client", mock_http1)
    client = platform_supabase._build_client(service=True)

    client.rpc("start_or_resume_video_learning_session", {"p_user_id": "u"}).execute()
    client.schema("public")  # must not switch the default for later unqualified calls
    client.rpc("claim_leased_content_work", {}).execute()

    for request in seen:
        assert request.url.path.startswith("/rest/v1/rpc/")
        assert request.headers["content-profile"] == "v3"


def test_requests_still_carry_project_url_and_service_key(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"code": "en"}])

    def mock_http1():
        return httpx.Client(http2=False, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(platform_supabase.settings, "SUPABASE_URL", URL)
    monkeypatch.setattr(platform_supabase.settings, "SUPABASE_SERVICE_ROLE_KEY", KEY)
    monkeypatch.setattr(platform_supabase, "_http1_client", mock_http1)
    client = platform_supabase._build_client(service=True)

    result = client.schema("v3").table("languages").select("code").execute()

    assert result.data == [{"code": "en"}]
    request = seen[0]
    assert str(request.url).startswith(f"{URL}/rest/v1/languages")
    assert request.headers["apikey"] == KEY
    assert request.headers["accept-profile"] == "v3"


def test_an_unconfigured_service_client_answers_503_instead_of_failing_later(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.bootstrap.wiring import clients
    from app.platform.process_clients import ProcessClientProxy

    unconfigured = ProcessClientProxy(type("Owner", (), {"client": None, "is_connected": lambda self: False})())
    monkeypatch.setattr(clients, "supabase_service", unconfigured)
    with pytest.raises(HTTPException) as error:
        clients.service_client()
    assert error.value.status_code == 503
