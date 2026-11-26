from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.learning.domain.companion import CompanionEntry
from tests.learning.test_companion import USER, make_service
from tests.learning.test_voice_consent_and_focus import choose, make_chooser


@pytest.mark.parametrize('other_words_due', [False, True])
def test_explicit_empty_due_notebook_stays_the_selected_topic(other_words_due):
    selected, other = uuid4(), uuid4()
    chooser, notebooks = make_chooser(due=[other] if other_words_due else [],
                                      notebooks={'Chosen': [selected], 'Other': [other]})
    result = choose(chooser, notebooks['Chosen'])
    assert result is not None and result.topic_id == notebooks['Chosen']
    assert result.title == 'Chosen' and result.items == []
    chooser.catalog.select.assert_not_called()


def test_free_conversation_with_an_explicit_empty_focus_does_not_fall_back_to_unrelated_words():
    service = make_service()
    topic_id = uuid4()
    service.focus = Mock()
    service.focus.choose.return_value = SimpleNamespace(title='Chosen', topic_id=topic_id, items=[])
    prepared = service.prepare(USER, CompanionEntry.HOME, None, topic_id=topic_id)
    assert prepared.ticket.topic == 'Chosen'
    assert prepared.ticket.items == ()
    assert not prepared.focused
