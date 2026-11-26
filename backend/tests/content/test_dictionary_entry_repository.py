from types import SimpleNamespace

from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository


class _Query:
    """Records filters and answers with fixed rows, like a PostgREST builder."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return record

    @property
    def not_(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows, count=len(self.rows))


class _Client:
    def __init__(self, rows):
        self.query = _Query(rows)

    def schema(self, _name):
        return self

    def table(self, _name):
        return self.query


def test_text_lookups_normalize_with_the_language():
    client = _Client([{"normalized_headword": "apple", "pronunciation": "/ˈæp.əl/", "definitions": []}])
    repository = DictionaryEntryRepository(client)

    assert repository.readings_for("en", ["Apple"]) == {"Apple": ("/ˈæp.əl/", None)}
    assert ("in_", ("normalized_headword", ["apple"])) in client.query.calls
    assert repository.has_headword("en", "Apple") is True
    assert ("eq", ("normalized_headword", "apple")) in client.query.calls
    assert repository.rows_containing("en", "App", limit=5)
    assert ("like", ("normalized_headword", "%app%")) in client.query.calls
