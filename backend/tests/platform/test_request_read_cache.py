"""Request-scoped read cache for shared content (app.platform.persistence)."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
from app.modules.content.infrastructure.repositories.videos import VideoRepository
from app.platform import persistence
from app.platform.persistence import request_read_cache


class FakeQuery:
    def __init__(self, client, table):
        self.client, self.table, self.operation = client, table, "select"

    def __getattr__(self, name):
        if name in {"insert", "update", "upsert", "delete"}:
            self.operation = name
        return lambda *args, **kwargs: self

    def execute(self):
        self.client.calls.append((self.table, self.operation))
        return type("Result", (), {"data": [dict(self.client.rows[self.table])]})()


class FakeClient:
    def __init__(self):
        self.calls = []
        self.rows = {
            "concepts": {"id": str(uuid4()), "language_code": "en", "type": "vocabulary", "canonical_text": "fly",
                         "normalized_text": "fly", "sense_key": "to travel by air", "metadata": {}},
            "videos": {"id": str(uuid4()), "source": "youtube", "external_video_id": "abc", "title": "t",
                       "original_language_code": "en"},
        }

    def schema(self, _name):
        return self

    def table(self, name):
        return FakeQuery(self, name)


def test_outside_a_request_every_read_reaches_the_database():
    client = FakeClient()
    concepts = ConceptRepository(client)
    concepts.get_by_id("x")
    concepts.get_by_id("x")
    assert client.calls == [("concepts", "select"), ("concepts", "select")]


def test_inside_a_request_a_repeated_read_is_served_once_and_copied_out():
    client = FakeClient()
    with request_read_cache():
        first = ConceptRepository(client).get_by_id("x")
        first.metadata["mutated"] = True
        second = ConceptRepository(client).get_by_id("x")  # another repository instance, same request
        assert client.calls == [("concepts", "select")]
        assert "mutated" not in second.metadata
        ConceptRepository(client).get_by_id("y")
    assert client.calls == [("concepts", "select"), ("concepts", "select")]


def test_any_other_query_on_the_table_drops_its_cached_reads_only():
    client = FakeClient()
    with request_read_cache():
        concepts, videos = ConceptRepository(client), VideoRepository(client)
        concepts.get_by_id("x")
        videos.get_by_id("v")
        concepts.table().upsert({}).execute()  # a write through the repository
        concepts.get_by_id("x")
        videos.get_by_id("v")
    assert client.calls == [("concepts", "select"), ("videos", "select"), ("concepts", "upsert"),
                            ("concepts", "select")]


def test_the_api_middleware_opens_one_cache_per_request():
    from app.bootstrap.api import create_app

    app = create_app()
    seen = []

    @app.get("/__cache_probe")
    def probe():
        cache = persistence._request_cache.get()
        seen.append(cache)
        return {"active": cache is not None}

    with TestClient(app) as client:
        assert client.get("/__cache_probe").json() == {"active": True}
        assert client.get("/__cache_probe").json() == {"active": True}
    assert seen[0] is not seen[1]
    assert persistence._request_cache.get() is None
