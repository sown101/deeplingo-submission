import pytest

from app.modules.learning.application.session_events import quote_is_grounded


@pytest.mark.parametrize("quote, turn, language", [
    ("我每天喝水, 也看书。", "我喜欢苹果。我每天喝水, 也看书。", "zh"),
    ("我每天 喝水 ， 也看书。", "我喜欢苹果。 我每天 喝水 ， 也看书。", "zh"),
    ("我喜欢苹果。", "我喜欢苹果。我每天喝水，也看书。", "zh"),
    ("Every day I drink water.", "I like apples. Every day I drink water and read a book.", "en"),
    ("I like apples. Every day I drink water and read a book.", "I like apples. Every day I drink water and read a book.", "en"),
])
def test_a_quote_is_grounded_when_it_is_the_learners_own_words_in_the_turn(quote, turn, language):
    assert quote_is_grounded(quote, turn, language)


@pytest.mark.parametrize("quote, turn, language", [
    ("A fabricated learner answer.", "I like apples.", "en"),
    ("apple", "I like pineapples.", "en"),
    ("我喜欢香蕉。", "我喜欢苹果。我每天喝水。", "zh"),
    ("", "我喜欢苹果。", "zh"),
    ("。", "我喜欢苹果。", "zh"),
])
def test_invented_or_partial_word_quotes_are_not_grounded(quote, turn, language):
    assert not quote_is_grounded(quote, turn, language)


def test_a_chinese_turn_quoted_by_clause_is_confirmed_instead_of_failing_the_whole_analysis():
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.modules.learning.application.session_events import ExtractedUses, SessionText, confirmed_uses

    apple, water = uuid4(), uuid4()
    now = datetime.now(UTC)
    data = SessionText(
        id=uuid4(), user_id=uuid4(), language_code="zh", context_key="probe", ended_at=now,
        targets=[{"concept_id": apple, "text": "苹果", "meaning": "apple", "forms": ["苹果"]},
                 {"concept_id": water, "text": "水", "meaning": "water", "forms": ["水"]}],
        turns=[{"occurred_at": now - timedelta(seconds=30), "text": "我喜欢苹果。我每天喝水, 也看书。"}])
    output = ExtractedUses.model_validate({"uses": [
        {"concept_id": apple, "turn": 0, "quote": "我喜欢苹果。", "used_form": "苹果", "correct_usage": True, "meaning_matches": True},
        {"concept_id": water, "turn": 0, "quote": "我每天喝水, 也看书。", "used_form": "水", "correct_usage": True, "meaning_matches": True}]})
    assert {use["concept_id"] for use in confirmed_uses(data, output)} == {str(apple), str(water)}


def test_a_use_whose_quote_does_not_hold_the_form_is_still_rejected():
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.modules.learning.application.session_events import ExtractedUses, SessionText, confirmed_uses

    water = uuid4()
    now = datetime.now(UTC)
    data = SessionText(
        id=uuid4(), user_id=uuid4(), language_code="zh", context_key="probe", ended_at=now,
        targets=[{"concept_id": water, "text": "水", "meaning": "water", "forms": ["水"]}],
        turns=[{"occurred_at": now - timedelta(seconds=30), "text": "我喜欢苹果。我每天喝水。"}])
    output = ExtractedUses.model_validate({"uses": [
        {"concept_id": water, "turn": 0, "quote": "我喜欢苹果。", "used_form": "水", "correct_usage": True, "meaning_matches": True}]})
    assert confirmed_uses(data, output) == []
