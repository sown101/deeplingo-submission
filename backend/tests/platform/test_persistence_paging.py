"""Large reads page through PostgREST's 1000-row response cap instead of silently stopping at it."""
from types import SimpleNamespace
from uuid import uuid4

from app.modules.content.infrastructure.repositories.saved_concepts import MAX_LISTED, SavedConceptRepository
from app.modules.practice.infrastructure.repositories import GrammarProgressRepository
import pytest

from app.platform.persistence import IN_CHUNK, PAGE_SIZE, SelectTooLarge, fetch_pages, select_rows

SERVER_CAP = 1000


class CappedQuery:
    """Answers like PostgREST: a `range` or `limit` never returns more than SERVER_CAP rows."""

    def __init__(self, rows, requests):
        self.rows, self.requests, self.window = rows, requests, (0, SERVER_CAP - 1)

    def __getattr__(self, name):  # select, eq, lte, order ...: filters do not matter to the paging
        return lambda *args, **kwargs: self

    def limit(self, count):
        self.window = (0, min(count, SERVER_CAP) - 1)
        return self

    def range(self, start, end):
        self.window = (start, min(end, start + SERVER_CAP - 1))
        return self

    def execute(self):
        start, end = self.window
        self.requests.append(self.window)
        return SimpleNamespace(data=self.rows[start:end + 1])


class CappedClient:
    def __init__(self, rows):
        self.rows, self.requests = rows, []

    def schema(self, _name):
        return self

    def table(self, _name):
        return CappedQuery(self.rows, self.requests)


def rows(count, **extra):
    return [{"n": index, **extra} for index in range(count)]


def test_fetch_pages_reads_every_page_until_a_short_one():
    client = CappedClient(rows(2500))
    found = fetch_pages(client.table("t"), 5000)
    assert len(found) == 2500 and [row["n"] for row in found] == list(range(2500))
    assert client.requests == [(0, 999), (1000, 1999), (2000, 2999)]


def test_fetch_pages_stops_at_the_callers_upper_bound():
    client = CappedClient(rows(2500))
    assert len(fetch_pages(client.table("t"), 1500)) == 1500
    assert client.requests == [(0, 999), (1000, 1499)]
    assert PAGE_SIZE == SERVER_CAP


def test_select_rows_returns_more_than_one_page():
    client = CappedClient(rows(2300))
    assert len(select_rows(client, "t", "n", filters={"user_id": "u"})) == 2300


def test_select_rows_reads_a_long_in_list_in_chunks_that_fit_a_url():
    sent: list[list[str]] = []

    class InQuery(CappedQuery):
        def in_(self, _column, values):
            sent.append(list(values))
            return self

    client = CappedClient(rows(3))
    client.table = lambda _name: InQuery(client.rows, client.requests)
    ids = [str(uuid4()) for _ in range(2 * IN_CHUNK + 50)]
    select_rows(client, "t", "n", filters={}, in_filter=("id", ids))
    assert [len(chunk) for chunk in sent] == [IN_CHUNK, IN_CHUNK, 50] and sum(sent, []) == ids
    assert select_rows(client, "t", "n", filters={}, in_filter=("id", [])) == []


def test_select_rows_refuses_more_rows_than_its_limit_instead_of_cutting_them():
    with pytest.raises(SelectTooLarge):
        select_rows(CappedClient(rows(2300)), "t", "n", filters={}, limit=2000)
    assert len(select_rows(CappedClient(rows(2000)), "t", "n", filters={}, limit=2000)) == 2000


def test_list_word_counts_are_not_cut_at_a_page():
    from app.modules.learner.infrastructure.word_groups import WordGroupItemRepository
    group = uuid4()
    client = CappedClient(rows(1500, group_id=str(group)))
    assert WordGroupItemRepository(client).counts([group]) == {group: 1500}


def test_the_saved_words_list_is_not_cut_at_a_page():
    client = CappedClient(rows(MAX_LISTED + 500))
    assert len(SavedConceptRepository(client).list_for_user(uuid4())) == MAX_LISTED


def test_grammar_progress_is_not_cut_at_a_page():
    grammar = [{"grammar_key": f"k{index}"} for index in range(1800)]
    assert len(GrammarProgressRepository(CappedClient(grammar)).for_language(uuid4(), "en")) == 1800
