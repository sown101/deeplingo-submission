import copy
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from postgrest.exceptions import APIError

# Request-scoped read cache for shared content (videos, transcripts, segments, Concepts ...).
# One learner request re-reads the same rows through several services; within a request
# they are a snapshot. The cache exists only inside `request_read_cache()` (the API
# middleware), so workers and scripts always read through. Any other query on a table
# (a write, or an uncached read) drops that table's cached entries.
_request_cache: ContextVar[dict | None] = ContextVar("v3_request_read_cache", default=None)
_inside_cached_read: ContextVar[bool] = ContextVar("v3_inside_cached_read", default=False)

F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def request_read_cache() -> Iterator[dict]:
    token = _request_cache.set({})
    try:
        yield _request_cache.get()
    finally:
        _request_cache.reset(token)


def cached_read(method: F) -> F:
    """Memoize a pure read of shared content for the current request (deep copies out)."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        cache = _request_cache.get()
        if cache is None:
            return method(self, *args, **kwargs)
        key = (self.table_name, method.__name__, repr(args), repr(sorted(kwargs.items())))
        if key in cache:
            return copy.deepcopy(cache[key])
        token = _inside_cached_read.set(True)
        try:
            value = method(self, *args, **kwargs)
        finally:
            _inside_cached_read.reset(token)
        cache[key] = copy.deepcopy(value)
        return value

    return wrapper  # type: ignore[return-value]


class V3Repository:
    schema = "v3"
    table_name: str

    def __init__(self, client: Any):
        self.client = client

    @property
    def qualified_table_name(self) -> str:
        return f"{self.schema}.{self.table_name}"

    def table(self) -> Any:
        cache = _request_cache.get()
        if cache is not None and not _inside_cached_read.get():
            for key in [key for key in cache if key[0] == self.table_name]:
                del cache[key]
        if hasattr(self.client, "schema"):
            return self.client.schema(self.schema).table(self.table_name)
        return self.client.table(self.qualified_table_name)



PAGE_SIZE = 1000  # PostgREST returns at most this many rows per request, whatever `limit` asks for


def fetch_pages(query: Any, limit: int) -> list[dict]:
    """Rows of `query` in pages of PAGE_SIZE, until a short page or `limit` rows. Order the query first when the
    result must not depend on the store's own order."""
    rows: list[dict] = []
    while len(rows) < limit:
        start = len(rows)
        size = min(PAGE_SIZE, limit - start)
        page = query.range(start, start + size - 1).execute().data or []
        rows.extend(page)
        if len(page) < size:
            break
    return rows


IN_CHUNK = 100  # ids per `in` filter: the ids travel in the request URL, which proxies and PostgREST bound
MAX_SELECT_ROWS = 100_000


class SelectTooLarge(RuntimeError):
    """More rows than `select_rows` may return: refused rather than silently cut."""


def select_rows(client: Any, table: str, columns: str, *, filters: dict[str, str], limit: int = MAX_SELECT_ROWS,
                in_filter: tuple[str, list[str]] | None = None, schema: str = "v3") -> list[dict]:
    """Plain filtered read used by per-module data exports; every filter is an equality. Every row is returned (a
    long `in` list is read in chunks); more than `limit` rows raise SelectTooLarge instead of being cut."""
    def query():
        built = (client.schema(schema).table(table) if hasattr(client, "schema")
                 else client.table(f"{schema}.{table}")).select(columns)
        for column, value in filters.items():
            built = built.eq(column, value)
        return built

    if in_filter is None:
        chunks: list = [None]
    else:
        column, values = in_filter
        # An empty `in` list makes no chunk and so returns no rows.
        chunks = [values[start:start + IN_CHUNK] for start in range(0, len(values), IN_CHUNK)]
    rows: list[dict] = []
    for chunk in chunks:
        built = query() if chunk is None else query().in_(column, chunk)
        rows.extend(fetch_pages(built, limit + 1 - len(rows)))
        if len(rows) > limit:
            raise SelectTooLarge(table)
    return rows


def select_optional_rows(client: Any, table: str, columns: str, *, filters: dict[str, str]) -> list[dict]:
    """Allow an older schema to omit a section, while propagating incomplete reads and outages."""
    try:
        return select_rows(client, table, columns, filters=filters)
    except APIError as exc:
        if exc.code not in {"42P01", "42703", "PGRST205"}:
            raise
        return []
