"""Lazy PID-owned clients, including compatibility aliases used by API/worker imports."""
import logging
import threading

import httpx
from postgrest import SyncPostgrestClient
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.platform.config import settings
from app.platform.process_clients import ProcessClientCache, ProcessClientProxy

logger = logging.getLogger(__name__)


# One process-owned client is shared by FastAPI's threadpool. A shared HTTP/2
# connection used from several threads failed reads with EAGAIN ("[Errno 11]"),
# so every sub-client goes through this explicit HTTP/1.1 pool instead.
SUPABASE_HTTP_TIMEOUT_SECONDS = 120.0
# Every backend RPC lives in v3, and repositories call `client.rpc(...)` unqualified.
# supabase 2.10's `client.schema()` silently switched the whole client's default
# schema, which is what used to route those RPCs; make the default explicit instead.
SUPABASE_DEFAULT_SCHEMA = "v3"


def _http1_client() -> httpx.Client:
    return httpx.Client(http2=False, timeout=SUPABASE_HTTP_TIMEOUT_SECONDS)


class _SchemaPooledClient:
    """Supabase client whose `schema(name)` reuses one PostgREST client per schema.

    postgrest-py's `schema()` builds a new client with a new HTTP/2 connection pool
    on every call and never closes it, which ignores the injected pool, re-handshakes
    TLS per query and leaks sockets in long-running processes. Repositories call
    `client.schema("v3")` per query, so cache per schema on the shared HTTP/1.1 pool.
    Every other attribute is the real Supabase client.
    """

    def __init__(self, client: Client, http_client: httpx.Client):
        self._client = client
        self._http_client = http_client
        self._schemas: dict[str, SyncPostgrestClient] = {}
        self._lock = threading.Lock()

    def schema(self, name: str) -> SyncPostgrestClient:
        with self._lock:
            scoped = self._schemas.get(name)
            if scoped is None:
                base = self._client.postgrest
                scoped = SyncPostgrestClient(
                    str(base.base_url), schema=name, headers=dict(base.headers), http_client=self._http_client,
                )
                self._schemas[name] = scoped
            return scoped

    def __getattr__(self, name):
        return getattr(self._client, name)


def _close_client(client):
    # Sync clients expose synchronous aclose/close. Avoid creating unused
    # network resources at shutdown. Hard-killed children rely on OS teardown.
    for resource, method in ((getattr(client, "_postgrest", None), "aclose"),
                             (getattr(client, "auth", None), "close"),
                             (getattr(getattr(client, "options", None), "httpx_client", None), "close")):
        if resource is not None and callable(getattr(resource, method, None)):
            try:
                getattr(resource, method)()
            except Exception:
                logger.warning("Supabase process resource close failed")


def _build_client(service):
    key = settings.SUPABASE_SERVICE_ROLE_KEY if service else settings.SUPABASE_KEY
    if not settings.SUPABASE_URL or not key:
        return None
    try:
        http_client = _http1_client()
        client = create_client(
            settings.SUPABASE_URL, key,
            options=SyncClientOptions(schema=SUPABASE_DEFAULT_SCHEMA, httpx_client=http_client),
        )
        return _SchemaPooledClient(client, http_client)
    except Exception:
        # Vendor messages can contain sensitive endpoints/keys.
        logger.error("Supabase process client initialization failed")
        raise RuntimeError("Supabase client initialization failed") from None


class SupabaseClient:
    _instance = None
    service = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_cache"):
            self._cache = ProcessClientCache(lambda: _build_client(self.service), _close_client)

    @property
    def client(self) -> Client | None:
        return self._cache.get()

    def is_connected(self) -> bool:
        return self.client is not None


class SupabaseServiceClient(SupabaseClient):
    _instance = None
    service = True


supabase_client = SupabaseClient()
supabase_service_client = SupabaseServiceClient()
supabase = ProcessClientProxy(supabase_client)
supabase_service = ProcessClientProxy(supabase_service_client)


def probe_database() -> bool:
    """Check PostgREST and PostgreSQL through a bounded, read-only request."""
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
    if not settings.SUPABASE_URL or not key:
        return False
    try:
        response = httpx.get(
            f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/languages",
            params={"select": "code", "limit": 1},
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": SUPABASE_DEFAULT_SCHEMA},
            timeout=0.75,
        )
        return response.is_success
    except (httpx.HTTPError, httpx.InvalidURL):
        return False


def close_process_clients():
    supabase_client._cache.shutdown()
    supabase_service_client._cache.shutdown()
