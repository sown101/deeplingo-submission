"""The study plan counts due cards of the plan's language only (it used to count every language)."""
from types import SimpleNamespace
from uuid import uuid4

from app.bootstrap.wiring.speaking import _DueConcepts, _DueInLanguage
from app.bootstrap.wiring.study_plan import REVIEW_COUNT_CAP, _ReviewReadiness

USER = SimpleNamespace(id=uuid4())


def readiness(english: int, chinese: int):
    concepts = [SimpleNamespace(id=uuid4(), language_code="en") for _ in range(english)]
    concepts += [SimpleNamespace(id=uuid4(), language_code="zh") for _ in range(chinese)]
    states = SimpleNamespace(list_due_for_user=lambda **kwargs: [SimpleNamespace(concept_id=c.id) for c in concepts])
    by_ids = SimpleNamespace(list_by_ids=lambda ids: [c for c in concepts if c.id in set(ids)])
    return _ReviewReadiness(_DueInLanguage(states, by_ids))


def test_due_cards_of_another_language_do_not_make_a_review_proposal():
    reviews = readiness(english=2, chinese=7)
    assert reviews.ready_count(USER, language_code="en") == 2
    assert reviews.ready_count(USER, language_code="zh") == 7
    assert readiness(english=0, chinese=5).ready_count(USER, language_code="en") == 0


def test_many_due_cards_of_another_language_do_not_hide_this_languages_cards():
    """The store returns at most `limit` due cards; 60 Chinese cards due first must not leave English at zero."""
    concepts = [SimpleNamespace(id=uuid4(), language_code="zh") for _ in range(60)]
    concepts += [SimpleNamespace(id=uuid4(), language_code="en") for _ in range(3)]

    def due(*, limit, language_code=None, **_):
        return [SimpleNamespace(concept_id=c.id) for c in concepts
                if language_code in (None, c.language_code)][:limit]

    by_ids = SimpleNamespace(list_by_ids=lambda ids: [c for c in concepts if c.id in set(ids)])
    reviews = _ReviewReadiness(_DueInLanguage(SimpleNamespace(list_due_for_user=due), by_ids))
    assert reviews.ready_count(USER, language_code="en") == 3


def test_the_count_is_capped_to_what_sizes_a_proposal() -> None:
    assert readiness(english=REVIEW_COUNT_CAP + 10, chinese=0).ready_count(USER, language_code="en") == REVIEW_COUNT_CAP


def test_the_companion_reads_due_words_of_its_language_before_the_limit():
    english = SimpleNamespace(concept_id=uuid4(), language_code="en")
    earlier = SimpleNamespace(concept_id=uuid4(), language_code="zh")

    def due(*, limit, language_code=None, **_):
        return [card for card in (earlier, english) if language_code in (None, card.language_code)][:limit]

    adapter = _DueConcepts(SimpleNamespace(list_due_for_user=due))
    assert adapter.due_concept_ids(USER.id, language_code="en", limit=1) == [str(english.concept_id)]
