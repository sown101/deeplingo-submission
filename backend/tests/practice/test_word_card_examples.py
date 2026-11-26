from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.modules.content.infrastructure.repositories.example_sentences import ExampleSentenceRepository
from app.modules.practice.infrastructure.word_cards import WordCards


def test_review_reads_fallback_examples_in_one_query_without_displacing_video_sentences():
    ids = [uuid4(), uuid4(), uuid4()]
    client = Mock()
    select = client.schema.return_value.table.return_value.select.return_value
    limited = select.in_.return_value.order.return_value.limit.return_value
    limited.execute.return_value.data = [
        {"id": str(key), "example_sentences": [
            {"concept_id": str(key), "language_code": "en", "text": "A generated sentence",
             "text_key": "generated", "target_form": "sentence", "source_kind": "generated"},
            {"concept_id": str(key), "language_code": "en", "text": "A corpus sentence",
             "text_key": "corpus", "target_form": "sentence", "source_kind": "corpus"},
        ]} for key in ids[1:]
    ]
    profiles = Mock()
    profiles.get_profile_for_user.return_value = SimpleNamespace(support_language_code="en")
    concepts = Mock()
    concepts.list_by_ids.return_value = [SimpleNamespace(id=key, language_code="en", canonical_text="sentence",
                                                          metadata={}) for key in ids]
    occurrences = Mock()
    occurrences.sentences_for.return_value = {ids[0]: SimpleNamespace(sentence="A video sentence",
        target_form="sentence", library_item_id=uuid4(), start_ms=10, part_of_speech=None)}
    cards = WordCards(profiles=profiles, concepts=concepts, meanings=None,
                      examples=ExampleSentenceRepository(client), occurrences=occurrences)

    result = cards.cards(uuid4(), "en", ids)

    assert [result[key].sentence.text for key in ids] == ["A video sentence", "A corpus sentence", "A corpus sentence"]
    select.in_.assert_called_once_with("id", [str(key) for key in ids[1:]])
    select.in_.return_value.order.assert_called_once_with("created_at", foreign_table="example_sentences")
    select.in_.return_value.order.return_value.limit.assert_called_once_with(12, foreign_table="example_sentences")
    limited.execute.assert_called_once_with()
