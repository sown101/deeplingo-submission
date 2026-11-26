"""L1b: named word lists, bulk import and the choice of a meaning (service level)."""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.modules.content.domain.knowledge import Concept, ConceptType
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application import word_lists
from app.modules.learner.application.word_lists import WordListError, WordListService
from app.modules.learner.domain.word_lists import SenseCandidate
from app.modules.learner.domain.word_targets import PRIORITY_IMPORT
from tests.learner.test_word_targets import USER, build

OTHER = CurrentUser(id=UUID("99999999-9999-9999-9999-999999999999"), role="authenticated", claims={})


class FakeGroups:
    def __init__(self):
        self.rows: dict[UUID, dict] = {}

    def create(self, user_id, *, language_code, name, description):
        row = {"id": str(uuid4()), "user_id": user_id, "language_code": language_code, "name": name,
               "description": description, "created_at": datetime(2026, 10, 26, tzinfo=UTC).isoformat()}
        self.rows[UUID(row["id"])] = row
        return dict(row)

    def list_for_user(self, user_id, *, language_code=None):
        return [dict(row) for row in self.rows.values()
                if row["user_id"] == user_id and (language_code is None or row["language_code"] == language_code)]

    def get(self, user_id, group_id):
        row = self.rows.get(group_id)
        return dict(row) if row and row["user_id"] == user_id else None

    def delete(self, user_id, group_id):
        row = self.rows.get(group_id)
        if row and row["user_id"] == user_id:
            del self.rows[group_id]
            return True
        return False


class FakeItems:
    def __init__(self):
        self.by_group: dict[UUID, list[UUID]] = {}

    def add(self, group_id, saved_concept_id):
        items = self.by_group.setdefault(group_id, [])
        if saved_concept_id in items:
            return False
        items.append(saved_concept_id)
        return True

    def saved_ids(self, group_id):
        return list(self.by_group.get(group_id, []))

    def remove(self, group_id, saved_concept_id):
        items = self.by_group.get(group_id, [])
        if saved_concept_id in items:
            items.remove(saved_concept_id)
            return True
        return False

    def counts(self, group_ids):
        return {item: len(self.by_group.get(item, [])) for item in group_ids}


class FakeRows:
    def __init__(self):
        self.rows: dict[UUID, dict] = {}

    def add(self, group_id, user_id, *, position, raw_text, user_gloss, resolution, candidates):
        row = {"id": str(uuid4()), "group_id": group_id, "position": position, "raw_text": raw_text,
               "user_gloss": user_gloss, "resolution": resolution, "candidates": candidates}
        self.rows[UUID(row["id"])] = row
        return dict(row)

    def _in(self, group_id):
        return sorted((row for row in self.rows.values() if row["group_id"] == group_id), key=lambda row: row["position"])

    def list(self, group_id):
        return [dict(row) for row in self._in(group_id)]

    def get(self, group_id, row_id):
        row = self.rows.get(row_id)
        return dict(row) if row and row["group_id"] == group_id else None

    def delete(self, group_id, row_id):
        if self.get(group_id, row_id) is None:
            return False
        del self.rows[row_id]
        return True

    def counts(self, group_ids):
        return {item: len(self._in(item)) for item in group_ids}

    def next_position(self, group_id):
        return max((row["position"] for row in self._in(group_id)), default=0) + 1

    def raw_words(self, group_id):
        return {row["raw_text"].casefold() for row in self._in(group_id)}


class FakeResolver:
    """Scripted dictionary: word -> meanings the server would find."""

    def __init__(self):
        self.table: dict[str, list[SenseCandidate]] = {}
        self.asked: list[list[str]] = []

    def candidates_for(self, language_code, words):
        self.asked.append(list(words))
        return {word: list(self.table.get(word.casefold(), [])) for word in words}


class FakeSenses:
    def __init__(self, resolver, *, level="A2"):
        self.resolver = resolver
        self.level = level
        self.made: dict[tuple, Concept] = {}
        self.fail = False

    def from_dictionary(self, *, language_code, entry_id, sense_id):
        if self.fail:
            raise ValueError("That meaning is not in this entry.")
        key = (entry_id, sense_id)
        if key not in self.made:
            headword = next(item.headword for items in self.resolver.table.values() for item in items
                            if (item.entry_id, item.sense_id) == key)
            self.made[key] = Concept(id=uuid4(), language_code=language_code, type=ConceptType.VOCABULARY, canonical_text=headword,
                                     normalized_text=headword, sense_key=f"{headword}:{sense_id}", difficulty_level=self.level,
                                     metadata={"sense_gloss": "a meaning"})
        return self.made[key]


def candidate(headword, sense="s1", text="A meaning."):
    return SenseCandidate(entry_id=uuid4(), sense_id=sense, headword=headword, text=text, part_of_speech="noun")


def make(*, level="A2", declared="A2"):
    env = build(declared=declared)
    resolver = FakeResolver()
    senses = FakeSenses(resolver, level=level)
    groups, items, rows = FakeGroups(), FakeItems(), FakeRows()
    concepts_seen = senses.made
    service = WordListService(
        groups=groups, items=items, rows=rows, targets_store=env.targets, targets=env.service, resolver=resolver,
        senses=senses, concepts=SimpleNamespace(list_by_ids=lambda ids: [c for c in concepts_seen.values() if c.id in ids]),
        preferences=env.service.preferences,
    )
    return SimpleNamespace(service=service, env=env, resolver=resolver, senses=senses, groups=groups, items=items, rows=rows)


def new_list(ctx, name="Travel", language="en", user=USER):
    return ctx.service.create(user, language_code=language, name=name)


# --- Lists ----------------------------------------------------------------------------------------

def test_a_list_is_created_listed_and_named_once_per_language():
    ctx = make()
    created = new_list(ctx)
    assert (created.name, created.word_count, created.waiting_count) == ("Travel", 0, 0)
    assert [item.name for item in ctx.service.list(USER, "en")] == ["Travel"] and ctx.service.list(USER, "zh") == []
    with pytest.raises(WordListError) as taken:
        new_list(ctx, name="  travel ")
    assert (taken.value.status_code, taken.value.code) == (409, "list_name_taken")
    with pytest.raises(WordListError) as language:
        new_list(ctx, language="fr")
    assert language.value.code == "language_not_learned"
    with pytest.raises(WordListError) as invalid:
        new_list(ctx, name="   ")
    assert invalid.value.code == "invalid_list_name"


def test_the_number_of_lists_is_limited(monkeypatch):
    monkeypatch.setattr(word_lists, "MAX_GROUPS_PER_LEARNER", 2)
    ctx = make()
    new_list(ctx, "One")
    new_list(ctx, "Two")
    with pytest.raises(WordListError) as error:
        new_list(ctx, "Three")
    assert (error.value.status_code, error.value.code) == (409, "too_many_lists")


def test_another_learners_list_is_never_visible_or_changeable():
    ctx = make()
    theirs = UUID(ctx.groups.create(OTHER.id, language_code="en", name="Theirs", description=None)["id"])
    for call in (lambda: ctx.service.detail(USER, theirs), lambda: ctx.service.delete(USER, theirs),
                 lambda: ctx.service.import_text(USER, theirs, "airport"),
                 lambda: ctx.service.add_word(USER, theirs, uuid4()),
                 lambda: ctx.service.dismiss_line(USER, theirs, uuid4()),
                 lambda: ctx.service.choose_meaning(USER, theirs, uuid4(), entry_id=uuid4(), sense_id="s1")):
        with pytest.raises(WordListError) as error:
            call()
        assert (error.value.status_code, error.value.code) == (404, "list_not_found")
    assert ctx.service.list(USER) == []


# --- Import ---------------------------------------------------------------------------------------

def test_import_makes_unique_meanings_active_words_and_keeps_the_rest_waiting():
    ctx = make()
    group = new_list(ctx)
    ctx.resolver.table = {"airport": [candidate("airport")],
                          "bank": [candidate("bank", "s1", "Where money is kept."), candidate("bank", "s2", "A river side.")]}
    report = ctx.service.import_text(USER, group.id, "airport\nbank, my money\nzzz\nairport")
    assert (report.matched, report.ambiguous, report.unresolved, report.duplicates) == (1, 1, 1, 1)
    airport = next(iter(ctx.env.targets.rows.values()))
    assert (airport["status"], airport["priority"], airport["save_source"], airport["explicit"]) == (
        "active", PRIORITY_IMPORT, "import", True)
    detail = ctx.service.detail(USER, group.id)
    assert [word.text for word in detail.words] == ["airport"]
    waiting = {line.text: line for line in detail.waiting}
    assert waiting["bank"].resolution == "ambiguous" and len(waiting["bank"].candidates) == 2
    assert waiting["bank"].gloss == "my money"
    assert waiting["zzz"].resolution == "unresolved" and waiting["zzz"].candidates == []
    assert (detail.word_count, detail.waiting_count) == (1, 2)


def test_importing_the_same_text_again_adds_nothing_twice():
    ctx = make()
    group = new_list(ctx)
    ctx.resolver.table = {"airport": [candidate("airport")], "bank": [candidate("bank"), candidate("bank", "s2")]}
    ctx.service.import_text(USER, group.id, "airport\nbank\nzzz")
    again = ctx.service.import_text(USER, group.id, "airport\nbank\nzzz")
    assert (again.matched, again.already_in_list, again.ambiguous, again.unresolved) == (0, 1, 0, 0)
    detail = ctx.service.detail(USER, group.id)
    assert (detail.word_count, detail.waiting_count) == (1, 2)
    assert ctx.resolver.asked[-1] == ["airport"]  # the waiting lines are not looked up again


def test_import_never_blocks_a_word_above_the_level_and_only_counts_it():
    ctx = make(level="C1", declared="A2")
    group = new_list(ctx)
    ctx.resolver.table = {"ubiquitous": [candidate("ubiquitous")]}
    report = ctx.service.import_text(USER, group.id, "ubiquitous")
    assert (report.matched, report.above_level) == (1, 1)
    assert ctx.service.detail(USER, group.id).words[0].above_level is True


def test_a_meaning_that_cannot_be_turned_into_a_word_waits_as_unresolved():
    ctx = make()
    group = new_list(ctx)
    ctx.resolver.table = {"airport": [candidate("airport")]}
    ctx.senses.fail = True
    report = ctx.service.import_text(USER, group.id, "airport")
    assert (report.matched, report.unresolved) == (0, 1)
    assert ctx.env.targets.rows == {}


def test_a_batch_reads_at_most_fifty_lines_and_a_full_list_stops_importing(monkeypatch):
    ctx = make()
    group = new_list(ctx)
    ctx.resolver.table = {f"w{n}": [candidate(f"w{n}")] for n in range(60)}
    report = ctx.service.import_text(USER, group.id, "\n".join(f"w{n}" for n in range(60)))
    assert (report.matched, report.over_limit) == (50, 10)
    monkeypatch.setattr(word_lists, "MAX_LIST_ROWS", 52)
    second = ctx.service.import_text(USER, group.id, "\n".join(f"w{n}" for n in range(50, 60)))
    assert second.matched == 2 and second.list_full is True
    existing = UUID(next(iter(ctx.env.targets.rows.values()))["concept_id"])
    with pytest.raises(WordListError) as full:
        ctx.service.add_word(USER, group.id, existing)
    assert (full.value.status_code, full.value.code) == (409, "list_full")


# --- Choosing a meaning ---------------------------------------------------------------------------

def test_the_learner_picks_one_of_the_stored_meanings_and_the_line_becomes_a_word():
    ctx = make()
    group = new_list(ctx)
    options = [candidate("bank", "s1", "Where money is kept."), candidate("bank", "s2", "A river side.")]
    ctx.resolver.table = {"bank": options}
    ctx.service.import_text(USER, group.id, "bank")
    line = ctx.service.detail(USER, group.id).waiting[0]
    word = ctx.service.choose_meaning(USER, group.id, line.id, entry_id=options[1].entry_id, sense_id="s2")
    assert word.text == "bank" and word.status == "active"
    detail = ctx.service.detail(USER, group.id)
    assert (detail.word_count, detail.waiting_count) == (1, 0)


def test_a_meaning_the_server_did_not_offer_is_refused_and_the_line_stays():
    ctx = make()
    group = new_list(ctx)
    options = [candidate("bank", "s1"), candidate("bank", "s2")]
    ctx.resolver.table = {"bank": options}
    ctx.service.import_text(USER, group.id, "bank")
    line = ctx.service.detail(USER, group.id).waiting[0]
    for entry_id, sense_id in ((uuid4(), "s1"), (options[0].entry_id, "s9")):
        with pytest.raises(WordListError) as error:
            ctx.service.choose_meaning(USER, group.id, line.id, entry_id=entry_id, sense_id=sense_id)
        assert (error.value.status_code, error.value.code) == (422, "sense_not_offered")
    assert ctx.service.detail(USER, group.id).waiting_count == 1
    assert ctx.env.targets.rows == {}
    with pytest.raises(WordListError) as missing:
        ctx.service.choose_meaning(USER, group.id, uuid4(), entry_id=options[0].entry_id, sense_id="s1")
    assert missing.value.code == "line_not_found"


def test_a_waiting_line_can_be_dismissed():
    ctx = make()
    group = new_list(ctx)
    ctx.service.import_text(USER, group.id, "zzz")
    line = ctx.service.detail(USER, group.id).waiting[0]
    ctx.service.dismiss_line(USER, group.id, line.id)
    assert ctx.service.detail(USER, group.id).waiting == []
    with pytest.raises(WordListError):
        ctx.service.dismiss_line(USER, group.id, line.id)


# --- Words in a list ------------------------------------------------------------------------------

def test_a_target_can_be_added_to_and_removed_from_a_list_and_deleting_the_list_keeps_the_words():
    ctx = make()
    group = new_list(ctx)
    ctx.resolver.table = {"airport": [candidate("airport")]}
    other = new_list(ctx, "Other")
    ctx.service.import_text(USER, group.id, "airport")
    concept_id = UUID(next(iter(ctx.env.targets.rows.values()))["concept_id"])
    ctx.service.add_word(USER, other.id, concept_id)
    assert ctx.service.detail(USER, other.id).word_count == 1
    ctx.service.remove_word(USER, other.id, concept_id)
    with pytest.raises(WordListError) as not_in_list:
        ctx.service.remove_word(USER, other.id, concept_id)
    assert not_in_list.value.code == "word_not_in_list"
    with pytest.raises(WordListError) as unknown:
        ctx.service.add_word(USER, other.id, uuid4())
    assert unknown.value.code == "word_not_found"
    ctx.service.delete(USER, group.id)
    assert len(ctx.env.targets.rows) == 1 and ctx.service.detail(USER, other.id).word_count == 0
