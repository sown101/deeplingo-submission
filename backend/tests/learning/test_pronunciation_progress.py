"""Stored pronunciation results hold numbers and weak words, and a storage failure never reaches the learner."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.modules.learning.application.speaking_activity import record_pronunciation


def result(score, weak=(), prosody=None):
    words = [SimpleNamespace(word=word, accuracy=40) for word in weak] + [SimpleNamespace(word="fine", accuracy=95)]
    return SimpleNamespace(scores=SimpleNamespace(pronunciation=score, accuracy=score, fluency=score, completeness=score,
                                                  prosody=prosody), words=words)


def test_a_practice_is_stored_as_averages_and_weak_words_only():
    store, user = Mock(), uuid4()
    record_pronunciation(store, user, language_code="en", source="jam",
                         results=[result(80, ["ship"], prosody=90), result(60, ["ship", "sheep"])])
    # Prosody averages only the results Azure scored it for.
    store.record.assert_called_once_with(user, language_code="en", source="jam", pronunciation=70.0, accuracy=70.0,
                                         fluency=70.0, completeness=70.0, prosody=90.0, weak_words=["ship", "sheep"])


def test_a_language_without_prosody_stores_it_empty():
    store, user = Mock(), uuid4()
    record_pronunciation(store, user, language_code="zh", source="jam", results=[result(75)])
    assert store.record.call_args.kwargs["prosody"] is None
    assert store.record.call_args.kwargs["completeness"] == 75.0


def test_nothing_is_stored_without_results_and_a_failure_is_swallowed():
    store = Mock()
    record_pronunciation(store, uuid4(), language_code="en", source="jam", results=[])
    store.record.assert_not_called()
    store.record.side_effect = RuntimeError("table missing")
    record_pronunciation(store, uuid4(), language_code="en", source="jam", results=[result(80)])
